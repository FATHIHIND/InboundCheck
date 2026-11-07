-- P0 corrective migration. Source only; operator approval and isolated SQL validation required.
-- Never stamp this version via legacy ledger reconciliation.
BEGIN;

-- Explicit least privilege, including column grants which table REVOKE does not remove.
DO $acl$
DECLARE t text; c text;
BEGIN
  FOREACH t IN ARRAY ARRAY['transactional_message_registry','delivery_failure_events','notification_outbox','profiles'] LOOP
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated', t);
    FOR c IN SELECT attname FROM pg_attribute
      WHERE attrelid = format('public.%I',t)::regclass AND attnum > 0 AND NOT attisdropped
    LOOP
      EXECUTE format('REVOKE INSERT (%I), UPDATE (%I), REFERENCES (%I) ON public.%I FROM PUBLIC, anon, authenticated',c,c,c,t);
    END LOOP;
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('GRANT SELECT ON TABLE public.%I TO authenticated',t);
    EXECUTE format('GRANT ALL ON TABLE public.%I TO postgres, service_role',t);
  END LOOP;
END;
$acl$;

-- Replace permissive write policies; trusted server roles retain their legitimate writes.
DO $policies$
DECLARE p record;
BEGIN
  FOR p IN SELECT tablename,policyname FROM pg_policies WHERE schemaname='public'
    AND tablename IN ('transactional_message_registry','delivery_failure_events','notification_outbox','profiles')
  LOOP
    EXECUTE format('DROP POLICY %I ON public.%I',p.policyname,p.tablename);
  END LOOP;
END;
$policies$;
CREATE POLICY p0_registry_owner_select ON public.transactional_message_registry
  FOR SELECT TO authenticated USING ((SELECT auth.uid())=user_id);
CREATE POLICY p0_delivery_event_owner_select ON public.delivery_failure_events
  FOR SELECT TO authenticated USING ((SELECT auth.uid())=user_id);
CREATE POLICY p0_outbox_owner_select ON public.notification_outbox
  FOR SELECT TO authenticated USING ((SELECT auth.uid())=user_id);
CREATE POLICY p0_profile_owner_select ON public.profiles
  FOR SELECT TO authenticated USING ((SELECT auth.uid())=id);
CREATE POLICY p0_profile_owner_update ON public.profiles
  FOR UPDATE TO authenticated USING ((SELECT auth.uid())=id) WITH CHECK ((SELECT auth.uid())=id);
GRANT UPDATE (full_name,avatar_url,company_name) ON public.profiles TO authenticated;
-- No INSERT policy/grant for clients: profile provisioning and repair are server-owned.

-- INVOKER is essential: current_user is now the actual SQL caller, not postgres
-- merely because this trigger function was SECURITY DEFINER. JWT role strings are
-- not an authorization source here. Trusted definer RPCs/provisioning run as postgres.
CREATE OR REPLACE FUNCTION public.protect_profile_billing_columns()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog
AS $guard$
BEGIN
  IF current_user IN ('postgres','supabase_admin','service_role') THEN RETURN NEW; END IF;
  IF TG_OP='INSERT' OR (
    NEW.subscription_tier IS DISTINCT FROM OLD.subscription_tier OR
    NEW.tier IS DISTINCT FROM OLD.tier OR
    NEW.subscription_status IS DISTINCT FROM OLD.subscription_status OR
    NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id OR
    NEW.stripe_subscription_id IS DISTINCT FROM OLD.stripe_subscription_id OR
    NEW.trial_ends_at IS DISTINCT FROM OLD.trial_ends_at OR
    NEW.current_period_end IS DISTINCT FROM OLD.current_period_end
  ) THEN
    RAISE EXCEPTION 'BILLING_WRITE_REQUIRES_TRUSTED_SQL_ROLE' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$guard$;
ALTER FUNCTION public.protect_profile_billing_columns() OWNER TO postgres;
REVOKE ALL ON FUNCTION public.protect_profile_billing_columns() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.protect_profile_billing_columns() TO postgres,service_role;
DROP TRIGGER IF EXISTS trg_protect_profile_billing_columns ON public.profiles;
CREATE TRIGGER trg_protect_profile_billing_columns BEFORE INSERT OR UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.protect_profile_billing_columns();
COMMIT;
