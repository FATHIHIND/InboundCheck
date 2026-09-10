-- File: supabase/migrations/20260912000002_add_delivery_failure_ingestion_and_idempotency.sql
-- Description: Delivery-failure ingestion, transactional message registry, and idempotency guarantees (Phase 4 Step 3)

-- =====================================================================
-- SECTION 1: TRANSACTIONAL MESSAGE REGISTRY
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.transactional_message_registry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  shopify_store_id UUID REFERENCES public.shopify_stores(id) ON DELETE SET NULL,
  order_id TEXT NOT NULL,
  esp_provider TEXT NOT NULL,
  provider_message_id TEXT NOT NULL,
  recipient_email_hash TEXT NOT NULL,
  recipient_phone_encrypted TEXT,
  phone_consent_status TEXT NOT NULL DEFAULT 'unknown'
    CHECK (phone_consent_status IN ('unknown', 'not_consented', 'consented', 'revoked')),
  message_type TEXT NOT NULL
    CHECK (message_type IN ('order_confirmation', 'shipping_update', 'delivery_update', 'password_reset')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (esp_provider, provider_message_id)
);

-- =====================================================================
-- SECTION 2: DELIVERY FAILURE EVENTS (INGESTION BUFFER)
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.delivery_failure_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  esp_provider TEXT NOT NULL,
  provider_event_id TEXT NOT NULL,
  provider_message_id TEXT,
  event_type TEXT NOT NULL,
  event_timestamp TIMESTAMPTZ,
  signature_verified BOOLEAN NOT NULL DEFAULT FALSE,
  processing_status TEXT NOT NULL DEFAULT 'received'
    CHECK (processing_status IN ('received', 'ignored', 'queued', 'processed', 'failed')),
  event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  UNIQUE (esp_provider, provider_event_id)
);

-- =====================================================================
-- SECTION 3: B-TREE INDEXES FOR HIGH-THROUGHPUT LOOKUPS & CORRELATION
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_transactional_message_provider_message
  ON public.transactional_message_registry(esp_provider, provider_message_id);

CREATE INDEX IF NOT EXISTS idx_transactional_message_user_order
  ON public.transactional_message_registry(user_id, order_id);

CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_processing
  ON public.delivery_failure_events(processing_status, received_at);

CREATE INDEX IF NOT EXISTS idx_delivery_failure_events_provider_msg
  ON public.delivery_failure_events(esp_provider, provider_message_id);

-- =====================================================================
-- SECTION 4: EXTEND FAILOVER_LOGS WITH CORRELATION & DISPATCH STATE
-- =====================================================================

ALTER TABLE public.failover_logs
  ADD COLUMN IF NOT EXISTS delivery_failure_event_id UUID
    REFERENCES public.delivery_failure_events(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS transactional_message_id UUID
    REFERENCES public.transactional_message_registry(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS order_id TEXT,
  ADD COLUMN IF NOT EXISTS fallback_channel TEXT
    CHECK (fallback_channel IN ('sms', 'whatsapp')),
  ADD COLUMN IF NOT EXISTS provider_sid TEXT,
  ADD COLUMN IF NOT EXISTS provider_status TEXT,
  ADD COLUMN IF NOT EXISTS provider_error_code TEXT,
  ADD COLUMN IF NOT EXISTS provider_error_message TEXT,
  ADD COLUMN IF NOT EXISTS attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS idx_failover_one_dispatch_per_event_channel
  ON public.failover_logs(delivery_failure_event_id, fallback_channel)
  WHERE delivery_failure_event_id IS NOT NULL;

-- =====================================================================
-- SECTION 5: ROW LEVEL SECURITY & PERMISSION POLICIES
-- =====================================================================

ALTER TABLE public.transactional_message_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delivery_failure_events ENABLE ROW LEVEL SECURITY;

-- 5.1 RLS Policies for transactional_message_registry
DROP POLICY IF EXISTS "Users access own transactional messages" ON public.transactional_message_registry;
CREATE POLICY "Users access own transactional messages"
  ON public.transactional_message_registry FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- 5.2 RLS Policies for delivery_failure_events
DROP POLICY IF EXISTS "Users access own delivery failure events" ON public.delivery_failure_events;
CREATE POLICY "Users access own delivery failure events"
  ON public.delivery_failure_events FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- 5.3 Service-role and authenticated grants
GRANT ALL ON public.transactional_message_registry TO authenticated;
GRANT ALL ON public.transactional_message_registry TO service_role;

GRANT ALL ON public.delivery_failure_events TO authenticated;
GRANT ALL ON public.delivery_failure_events TO service_role;
