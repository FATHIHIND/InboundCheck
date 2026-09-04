-- =====================================================================
-- InboundCheck Migration 005: Fix handle_new_user Trigger & Profile RLS
-- File: supabase/migrations/20260904000001_fix_handle_new_user_trigger.sql
-- =====================================================================
-- Root Cause Addressed:
-- 1. gen_random_bytes(24) was failing when pgcrypto is in schema extensions
--    because SECURITY DEFINER did not have search_path configured.
-- 2. Fixed public.profiles.api_key column default to not rely on extensions search_path.
-- 3. Added search_path = public, extensions, pg_temp to handle_new_user().
-- 4. Added safe exception trapping so unexpected edge cases do not abort auth.users.
-- 5. Added explicit RLS policy granting service_role and trigger access.
-- =====================================================================

-- 1. Ensure pgcrypto extension is installed in schema extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA extensions;

-- 2. Fix public.profiles api_key default to be immune to missing search_path
ALTER TABLE public.profiles 
    ALTER COLUMN api_key SET DEFAULT ('ic_live_' || replace(gen_random_uuid()::text, '-', '') || substr(replace(gen_random_uuid()::text, '-', ''), 1, 16));

-- 3. Provisioning Trigger Function with explicit search_path and error shielding
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions, pg_temp
AS $$
DECLARE
  v_full_name TEXT;
  v_avatar_url TEXT;
  v_company_name TEXT;
  v_api_key TEXT;
BEGIN
  -- Extract metadata with graceful fallbacks
  v_full_name := COALESCE(
    NEW.raw_user_meta_data->>'full_name',
    NEW.raw_user_meta_data->>'name',
    split_part(NEW.email, '@', 1)
  );
  v_avatar_url := COALESCE(
    NEW.raw_user_meta_data->>'avatar_url',
    NEW.raw_user_meta_data->>'picture',
    NULL
  );
  v_company_name := COALESCE(
    NEW.raw_user_meta_data->>'company_name',
    NULL
  );

  -- Generate resilient API key
  BEGIN
    v_api_key := 'ic_live_' || encode(extensions.gen_random_bytes(24), 'hex');
  EXCEPTION WHEN OTHERS THEN
    v_api_key := 'ic_live_' || replace(gen_random_uuid()::text, '-', '') || substr(replace(gen_random_uuid()::text, '-', ''), 1, 16);
  END;

  -- Remove any orphan profile with the same email to avoid unique constraint collision
  IF NEW.email IS NOT NULL THEN
    DELETE FROM public.profiles WHERE email = NEW.email AND id <> NEW.id;
  END IF;

  -- Upsert profile record
  INSERT INTO public.profiles (
    id,
    email,
    full_name,
    avatar_url,
    company_name,
    api_key,
    tier
  )
  VALUES (
    NEW.id,
    COALESCE(NEW.email, NEW.id::text || '@inboundcheck.internal'),
    v_full_name,
    v_avatar_url,
    v_company_name,
    v_api_key,
    'starter'
  )
  ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    full_name = COALESCE(EXCLUDED.full_name, public.profiles.full_name),
    avatar_url = COALESCE(EXCLUDED.avatar_url, public.profiles.avatar_url),
    company_name = COALESCE(EXCLUDED.company_name, public.profiles.company_name),
    updated_at = NOW();

  RETURN NEW;
EXCEPTION
  WHEN OTHERS THEN
    -- Prevent aborting auth.users insert transaction; log error to Postgres logs
    RAISE WARNING 'handle_new_user trigger encountered an error for user %: % (SQLSTATE %)', NEW.id, SQLERRM, SQLSTATE;
    RETURN NEW;
END;
$$;

-- 4. Set owner to postgres
ALTER FUNCTION public.handle_new_user() OWNER TO postgres;

-- 5. Recreate trigger on auth.users
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 6. Permissions and RLS policies
GRANT ALL ON TABLE public.profiles TO postgres, service_role;
GRANT SELECT, UPDATE, INSERT ON TABLE public.profiles TO authenticated;

DROP POLICY IF EXISTS "Service role and trigger full access" ON public.profiles;
CREATE POLICY "Service role and trigger full access"
    ON public.profiles
    FOR ALL
    TO service_role, postgres
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Users can insert their own profile" ON public.profiles;
CREATE POLICY "Users can insert their own profile"
    ON public.profiles FOR INSERT
    WITH CHECK (auth.uid() = id OR auth.uid() IS NULL);
