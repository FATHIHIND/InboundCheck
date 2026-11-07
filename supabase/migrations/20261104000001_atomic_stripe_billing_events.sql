-- INV-14 SOURCE ONLY: review separately; do not apply as part of source authoring.
BEGIN;

CREATE TABLE public.stripe_billing_events (
    event_id text PRIMARY KEY,
    event_type text NOT NULL,
    event_created bigint NOT NULL CHECK (event_created >= 0),
    payload_hash text NOT NULL,
    user_id uuid REFERENCES public.profiles(id) ON DELETE CASCADE,
    result jsonb,
    completed_at timestamptz,
    CHECK ((result IS NULL) = (completed_at IS NULL))
);
CREATE TABLE public.stripe_billing_watermarks (
    user_id uuid PRIMARY KEY REFERENCES public.profiles(id) ON DELETE CASCADE,
    event_created bigint NOT NULL CHECK (event_created >= 0),
    event_id text NOT NULL REFERENCES public.stripe_billing_events(event_id),
    subscription_id text NOT NULL,
    retired_subscription_ids text[] NOT NULL DEFAULT ARRAY[]::text[]
);
ALTER TABLE public.stripe_billing_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stripe_billing_watermarks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stripe_billing_events, public.stripe_billing_watermarks FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.stripe_billing_events, public.stripe_billing_watermarks TO service_role;
-- No end-user policies. Service-role RPC is the sole application write path.

CREATE FUNCTION public.process_stripe_billing_event(p_event jsonb, p_prices jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    v_id text := p_event->>'id';
    v_type text := p_event->>'type';
    v_created bigint;
    v_hash text;
    v_claimed text;
    v_previous public.stripe_billing_events%ROWTYPE;
    v_profile public.profiles%ROWTYPE;
    v_watermark public.stripe_billing_watermarks%ROWTYPE;
    v_obj jsonb := p_event #> '{data,object}';
    v_customer text;
    v_subscription text;
    v_checkout boolean;
    v_status text;
    v_downgrade boolean;
    v_items jsonb;
    v_price text;
    v_tier text;
    v_matches integer;
    v_period timestamptz;
    v_retired text[];
    v_result jsonb;
BEGIN
    -- Privilege check remains explicit as defense in depth; SQL errors cause
    -- PostgREST to fail the RPC and roll back its entire transaction.
    IF current_user NOT IN ('postgres', 'supabase_admin') THEN
        RAISE EXCEPTION 'Atomic Stripe function owner must be privileged' USING ERRCODE = '42501';
    END IF;
    IF v_type IS NULL OR v_type NOT IN ('checkout.session.completed', 'customer.subscription.updated', 'customer.subscription.deleted') THEN
        RETURN jsonb_build_object('status', 'ignored', 'event_type', v_type);
    END IF;
    IF v_id IS NULL OR v_id = '' OR jsonb_typeof(p_event->'created') IS DISTINCT FROM 'number'
       OR (p_event->>'created') !~ '^[0-9]+$' THEN
        RAISE EXCEPTION 'Stripe event id and integer created are required' USING ERRCODE = '22023';
    END IF;
    v_created := (p_event->>'created')::bigint;
    -- Hash the canonical JSONB representation; never persist Stripe payload/PII.
    v_hash := encode(sha256(convert_to(p_event::text, 'UTF8')), 'hex');
    -- The PK claim serializes concurrent duplicates. A transaction failure rolls
    -- back this claim along with profile/watermark changes, allowing safe retry.
    INSERT INTO public.stripe_billing_events(event_id,event_type,event_created,payload_hash)
    VALUES(v_id,v_type,v_created,v_hash)
    ON CONFLICT (event_id) DO NOTHING RETURNING event_id INTO v_claimed;
    IF v_claimed IS NULL THEN
        SELECT * INTO STRICT v_previous FROM public.stripe_billing_events WHERE event_id = v_id FOR UPDATE;
        IF v_previous.payload_hash <> v_hash THEN
            RAISE EXCEPTION 'Conflicting payload for existing Stripe event id' USING ERRCODE = '22023';
        END IF;
        IF v_previous.completed_at IS NULL OR v_previous.result IS NULL THEN
            RAISE EXCEPTION 'Incomplete event requires reconciliation; retry required' USING ERRCODE = '40001';
        END IF;
        RETURN jsonb_build_object('status','already_processed','idempotent',true,'event_id',v_id,'result',v_previous.result);
    END IF;
    -- Cutover: a committed legacy event is already known to have been handled.
    -- Preserve that fact durably without replaying profile changes or advancing
    -- a watermark from a delivery timestamp. The legacy ledger has no hash or
    -- original result, so this first observation records only a synthetic ignore.
    IF EXISTS (SELECT 1 FROM public.processed_webhook_events WHERE id = v_id) THEN
        v_result := jsonb_build_object('status','ignored','event_type',v_type,'reason','legacy_processed');
        UPDATE public.stripe_billing_events SET result = v_result, completed_at = clock_timestamp() WHERE event_id = v_id;
        RETURN jsonb_build_object('status','already_processed','idempotent',true,'event_id',v_id,'result',v_result);
    END IF;
    -- Legacy cleanup removes entries after 48 hours. Absence is NOT proof that
    -- an event is new: reconcile initial provider state/watermarks before live
    -- cutover. Never seed a NOW() watermark that discards legitimate pending events.
    v_customer := CASE WHEN jsonb_typeof(v_obj->'customer') = 'object' THEN v_obj #>> '{customer,id}' ELSE v_obj->>'customer' END;
    IF v_customer IS NULL OR v_customer = '' THEN
        RAISE EXCEPTION 'Stripe customer is required' USING ERRCODE = '22023';
    END IF;
    -- Never resolve by email or trust metadata to establish ownership. Existing
    -- server-created customer mapping is mandatory, even for initial checkout.
    BEGIN
        SELECT * INTO STRICT v_profile FROM public.profiles WHERE stripe_customer_id = v_customer FOR UPDATE;
    EXCEPTION WHEN no_data_found OR too_many_rows THEN
        RAISE EXCEPTION 'Stripe customer must have a unique server-side mapping' USING ERRCODE = '22023';
    END;
    IF (nullif(v_obj #>> '{metadata,user_id}','') IS NOT NULL AND v_obj #>> '{metadata,user_id}' <> v_profile.id::text)
       OR (nullif(v_obj->>'client_reference_id','') IS NOT NULL AND v_obj->>'client_reference_id' <> v_profile.id::text) THEN
        RAISE EXCEPTION 'Stripe tenant metadata conflicts with customer mapping' USING ERRCODE = '22023';
    END IF;
    -- profiles FOR UPDATE is the per-tenant serialization lock, including the
    -- first event where a watermark row does not yet exist.
    SELECT * INTO v_watermark FROM public.stripe_billing_watermarks WHERE user_id = v_profile.id FOR UPDATE;
    IF FOUND THEN
        IF v_created = v_watermark.event_created THEN
            RAISE EXCEPTION 'Equal Stripe timestamps require authoritative reconciliation; retry required' USING ERRCODE = '40001';
        ELSIF v_created < v_watermark.event_created THEN
            v_result := jsonb_build_object('status','ignored','event_type',v_type,'reason','stale_event');
        END IF;
    END IF;
    IF v_result IS NULL THEN
        v_checkout := v_type = 'checkout.session.completed';
        v_subscription := CASE WHEN v_checkout THEN
            CASE WHEN jsonb_typeof(v_obj->'subscription') = 'object' THEN v_obj #>> '{subscription,id}' ELSE v_obj->>'subscription' END
            ELSE v_obj->>'id' END;
        IF v_subscription IS NULL OR v_subscription = '' THEN
            RAISE EXCEPTION 'Stripe subscription id is required' USING ERRCODE = '22023';
        END IF;
        v_retired := coalesce(v_watermark.retired_subscription_ids, ARRAY[]::text[]);
        IF v_subscription = ANY(v_retired) THEN
            RAISE EXCEPTION 'Retired subscription requires authoritative reconciliation; retry required' USING ERRCODE = '40001';
        END IF;
        -- A later notification for a retired subscription cannot overwrite the
        -- subscription established by newer checkout, regardless of timestamp.
        IF NOT v_checkout AND v_profile.stripe_subscription_id IS NOT NULL
           AND v_profile.stripe_subscription_id <> v_subscription THEN
            RAISE EXCEPTION 'Different subscription requires authoritative reconciliation; retry required' USING ERRCODE = '40001';
        END IF;
        IF v_checkout THEN
            IF v_obj->>'mode' IS DISTINCT FROM 'subscription' OR coalesce(v_obj->>'payment_status','') NOT IN ('paid','no_payment_required') THEN
                RAISE EXCEPTION 'Checkout must be subscription mode and paid or require no payment' USING ERRCODE = '22023';
            END IF;
            v_status := CASE WHEN jsonb_typeof(v_obj->'subscription') = 'object' THEN v_obj #>> '{subscription,status}' END;
            IF v_status IS NOT NULL AND v_status NOT IN ('active','trialing') THEN
                RAISE EXCEPTION 'Checkout subscription is not active or trialing' USING ERRCODE = '22023';
            END IF;
            -- no_payment_required is Stripe-confirmed zero-payment completion,
            -- not unpaid. Do not infer trialing without subscription evidence.
            v_status := coalesce(v_status,'active');
        ELSE
            v_status := v_obj->>'status';
        END IF;
        v_downgrade := v_type = 'customer.subscription.deleted' OR coalesce(v_status IN ('canceled','unpaid'),false);
        IF NOT v_downgrade AND (v_status IS NULL OR v_status NOT IN ('active','past_due','trialing')) THEN
            v_result := jsonb_build_object('status','ignored','event_type',v_type);
        ELSE
            IF v_downgrade THEN
                v_tier := 'starter';
                v_status := CASE WHEN v_status = 'canceled' THEN 'canceled' ELSE 'expired' END;
            ELSE
                v_items := CASE WHEN v_checkout THEN v_obj #> '{line_items,data}' ELSE v_obj #> '{items,data}' END;
                IF v_checkout AND (v_items IS NULL OR v_items = '[]'::jsonb) THEN
                    v_items := v_obj #> '{subscription,items,data}';
                END IF;
                IF v_checkout AND (v_items IS NULL OR v_items = '[]'::jsonb) THEN
                    -- Trust boundary: the backend checkout API authors these
                    -- metadata values; this RPC accepts only signed events
                    -- through service_role after customer/tenant binding above.
                    -- Clients cannot choose arbitrary tiers or configured prices.
                    v_tier := coalesce(nullif(v_obj #>> '{metadata,subscription_tier}',''),nullif(v_obj #>> '{metadata,plan_tier}',''));
                    IF v_tier IS NULL OR v_tier NOT IN ('starter','growth','agency') OR coalesce(p_prices->>v_tier,'') = '' THEN
                        RAISE EXCEPTION 'Checkout metadata must name an exact configured server tier' USING ERRCODE = '22023';
                    END IF;
                    IF (nullif(v_obj #>> '{metadata,subscription_tier}','') IS NOT NULL AND v_obj #>> '{metadata,subscription_tier}' <> v_tier)
                       OR (nullif(v_obj #>> '{metadata,plan_tier}','') IS NOT NULL AND v_obj #>> '{metadata,plan_tier}' <> v_tier) THEN
                        RAISE EXCEPTION 'Checkout metadata tiers conflict' USING ERRCODE = '22023';
                    END IF;
                ELSE
                    IF jsonb_typeof(v_items) IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION 'Expanded Stripe subscription price is required' USING ERRCODE = '22023';
                    END IF;
                    IF jsonb_array_length(v_items) <> 1 THEN
                        RAISE EXCEPTION 'Exactly one Stripe subscription price is required' USING ERRCODE = '22023';
                    END IF;
                    v_price := CASE WHEN jsonb_typeof(v_items #> '{0,price}') = 'object' THEN v_items #>> '{0,price,id}' ELSE v_items #>> '{0,price}' END;
                    SELECT count(*), min(key) INTO v_matches,v_tier FROM jsonb_each_text(p_prices)
                      WHERE key IN ('starter','growth','agency') AND value <> '' AND value = v_price;
                    IF v_matches <> 1 THEN
                        RAISE EXCEPTION 'Unknown or ambiguous server Stripe price' USING ERRCODE = '22023';
                    END IF;
                END IF;
            END IF;
            IF v_obj->'current_period_end' IS NOT NULL AND v_obj->'current_period_end' <> 'null'::jsonb THEN
                IF jsonb_typeof(v_obj->'current_period_end') <> 'number' OR (v_obj->>'current_period_end') !~ '^[0-9]+$' THEN
                    RAISE EXCEPTION 'Invalid subscription current_period_end' USING ERRCODE = '22023';
                END IF;
                v_period := to_timestamp((v_obj->>'current_period_end')::bigint);
            END IF;
            UPDATE public.profiles SET subscription_tier = v_tier, tier = v_tier,
                subscription_status = v_status, stripe_subscription_id = v_subscription,
                current_period_end = coalesce(v_period,current_period_end), updated_at = clock_timestamp()
                WHERE id = v_profile.id;
            IF v_profile.stripe_subscription_id IS NOT NULL AND v_profile.stripe_subscription_id <> v_subscription THEN
                v_retired := array_append(v_retired, v_profile.stripe_subscription_id);
            END IF;
            INSERT INTO public.stripe_billing_watermarks(user_id,event_created,event_id,subscription_id,retired_subscription_ids)
            VALUES(v_profile.id,v_created,v_id,v_subscription,v_retired)
            ON CONFLICT (user_id) DO UPDATE SET event_created = EXCLUDED.event_created,
                event_id = EXCLUDED.event_id, subscription_id = EXCLUDED.subscription_id,
                retired_subscription_ids = EXCLUDED.retired_subscription_ids;
            IF v_checkout THEN
                v_result := jsonb_build_object('status','success','action','subscription_activated','user_id',v_profile.id,
                    'subscription_tier',v_tier,'tier',v_tier,'customer_id',v_customer);
            ELSE
                v_result := jsonb_build_object('status','success','action',CASE WHEN v_downgrade THEN 'subscription_downgraded' ELSE 'subscription_updated' END,
                    'user_id',v_profile.id,'subscription_status',v_status);
            END IF;
        END IF;
    END IF;
    UPDATE public.stripe_billing_events SET user_id = v_profile.id, result = v_result, completed_at = clock_timestamp() WHERE event_id = v_id;
    RETURN v_result;
END;
$function$;
ALTER FUNCTION public.process_stripe_billing_event(jsonb,jsonb) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.process_stripe_billing_event(jsonb,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.process_stripe_billing_event(jsonb,jsonb) TO service_role;
COMMIT;
