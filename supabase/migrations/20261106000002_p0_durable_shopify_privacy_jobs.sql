-- P0 local corrective migration: durable, minimized Shopify privacy acceptance.
-- SOURCE ONLY. Apply only after explicit environment/migration authorization and isolated SQL validation.
BEGIN;

CREATE TABLE IF NOT EXISTS public.shopify_privacy_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id text NOT NULL UNIQUE CHECK (event_id ~ '^[A-Za-z0-9_-]{1,200}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  shop_domain text NOT NULL,
  user_id uuid NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK (kind IN ('customers/data_request','customers/redact','shop/redact')),
  subject_hash text NULL CHECK (subject_hash IS NULL OR subject_hash ~ '^[0-9a-f]{64}$'),
  customer_id_hash text NULL CHECK (customer_id_hash IS NULL OR customer_id_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','processing','completed','failed','requires_manual_review')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  claimed_by uuid NULL,
  lease_expires_at timestamptz NULL,
  last_error_code text NULL CHECK (last_error_code IS NULL OR last_error_code ~ '^[a-z0-9_]{1,64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz NULL,
  CONSTRAINT shopify_privacy_jobs_request_identity UNIQUE (shop_domain, request_hash)
);
CREATE INDEX IF NOT EXISTS shopify_privacy_jobs_claim_idx ON public.shopify_privacy_jobs (state, lease_expires_at, created_at);
CREATE INDEX IF NOT EXISTS shopify_privacy_jobs_user_idx ON public.shopify_privacy_jobs (user_id, created_at DESC);
ALTER TABLE public.shopify_privacy_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.shopify_privacy_jobs FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.shopify_privacy_jobs TO service_role, postgres;

CREATE OR REPLACE FUNCTION public.enqueue_privacy_job(
  p_event_id text, p_request_hash text, p_shop_domain text, p_kind text,
  p_subject_hash text DEFAULT NULL, p_customer_id text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_job public.shopify_privacy_jobs; v_user_id uuid; v_inserted integer := 0;
BEGIN
  IF current_user NOT IN ('postgres','service_role') THEN RAISE EXCEPTION 'trusted service role required' USING ERRCODE='42501'; END IF;
  SELECT user_id INTO v_user_id FROM public.shopify_stores
    WHERE lower(shop_domain) = lower(p_shop_domain) ORDER BY updated_at DESC LIMIT 1;
  IF v_user_id IS NULL THEN RAISE EXCEPTION 'verified shop is not registered' USING ERRCODE='P0001'; END IF;
  INSERT INTO public.shopify_privacy_jobs(event_id,request_hash,shop_domain,user_id,kind,subject_hash,customer_id_hash)
  VALUES (p_event_id,p_request_hash,lower(p_shop_domain),v_user_id,p_kind,p_subject_hash,p_customer_id)
  ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  SELECT * INTO v_job FROM public.shopify_privacy_jobs WHERE event_id=p_event_id;
  IF FOUND THEN
    IF v_job.request_hash <> p_request_hash OR v_job.shop_domain <> lower(p_shop_domain) OR v_job.kind <> p_kind THEN
      RAISE EXCEPTION 'privacy event identifier was reused with a different request' USING ERRCODE='P0001';
    END IF;
  ELSE
    SELECT * INTO v_job FROM public.shopify_privacy_jobs WHERE shop_domain=lower(p_shop_domain) AND request_hash=p_request_hash;
  END IF;
  IF NOT FOUND THEN RAISE EXCEPTION 'privacy job acceptance failed' USING ERRCODE='P0001'; END IF;
  RETURN jsonb_build_object('status','accepted','job_id',v_job.id,'state',v_job.state,'idempotent',v_inserted = 0);
END $$;

CREATE OR REPLACE FUNCTION public.claim_privacy_jobs(p_worker_id uuid,p_limit integer DEFAULT 1,p_lease_seconds integer DEFAULT 120)
RETURNS TABLE(id uuid, claimed_by uuid, state text, kind text) LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
  IF current_user NOT IN ('postgres','service_role') THEN RAISE EXCEPTION 'trusted service role required' USING ERRCODE='42501'; END IF;
  IF p_limit < 1 OR p_limit > 10 OR p_lease_seconds < 30 OR p_lease_seconds > 900 THEN RAISE EXCEPTION 'invalid claim bounds' USING ERRCODE='22023'; END IF;
  RETURN QUERY WITH candidates AS (
    SELECT j.id FROM public.shopify_privacy_jobs j
    WHERE j.state='queued' OR (j.state='processing' AND j.lease_expires_at < now())
    ORDER BY j.created_at FOR UPDATE SKIP LOCKED LIMIT p_limit
  ), claimed AS (
    UPDATE public.shopify_privacy_jobs j SET state='processing',claimed_by=p_worker_id,lease_expires_at=now()+make_interval(secs=>p_lease_seconds),attempt_count=j.attempt_count+1,updated_at=now()
    FROM candidates c WHERE j.id=c.id RETURNING j.id,j.claimed_by,j.state,j.kind
  ) SELECT * FROM claimed;
END $$;

CREATE OR REPLACE FUNCTION public.execute_privacy_job(p_job_id uuid,p_worker_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_job public.shopify_privacy_jobs;
BEGIN
  IF current_user NOT IN ('postgres','service_role') THEN RAISE EXCEPTION 'trusted service role required' USING ERRCODE='42501'; END IF;
  SELECT * INTO v_job FROM public.shopify_privacy_jobs WHERE id=p_job_id FOR UPDATE;
  IF NOT FOUND OR v_job.claimed_by IS DISTINCT FROM p_worker_id OR v_job.state <> 'processing' OR v_job.lease_expires_at < now() THEN RAISE EXCEPTION 'privacy lease unavailable' USING ERRCODE='P0001'; END IF;
  -- No data export/erasure adapter is approved here. Never synthesize a completion.
  UPDATE public.shopify_privacy_jobs SET state='requires_manual_review',completed_at=now(),lease_expires_at=NULL,updated_at=now(),last_error_code='adapter_not_authorized' WHERE id=p_job_id;
  RETURN jsonb_build_object('status','requires_manual_review','job_id',p_job_id);
END $$;

CREATE OR REPLACE FUNCTION public.fail_privacy_job(p_job_id uuid,p_worker_id uuid,p_error_code text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_job public.shopify_privacy_jobs;
BEGIN
  IF current_user NOT IN ('postgres','service_role') THEN RAISE EXCEPTION 'trusted service role required' USING ERRCODE='42501'; END IF;
  SELECT * INTO v_job FROM public.shopify_privacy_jobs WHERE id=p_job_id FOR UPDATE;
  IF NOT FOUND OR v_job.claimed_by IS DISTINCT FROM p_worker_id OR v_job.state <> 'processing' THEN RAISE EXCEPTION 'privacy lease unavailable' USING ERRCODE='P0001'; END IF;
  UPDATE public.shopify_privacy_jobs SET state=CASE WHEN attempt_count >= 3 THEN 'requires_manual_review' ELSE 'queued' END, claimed_by=NULL,lease_expires_at=NULL,last_error_code=CASE WHEN p_error_code ~ '^[a-z0-9_]{1,64}$' THEN p_error_code ELSE 'execution_unconfirmed' END,updated_at=now() WHERE id=p_job_id
  RETURNING * INTO v_job;
  RETURN jsonb_build_object('status',v_job.state,'job_id',v_job.id,'attempt_count',v_job.attempt_count);
END $$;

REVOKE ALL ON FUNCTION public.enqueue_privacy_job(text,text,text,text,text,text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.claim_privacy_jobs(uuid,integer,integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.execute_privacy_job(uuid,uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fail_privacy_job(uuid,uuid,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_privacy_job(text,text,text,text,text,text), public.claim_privacy_jobs(uuid,integer,integer), public.execute_privacy_job(uuid,uuid), public.fail_privacy_job(uuid,uuid,text) TO service_role, postgres;
COMMIT;