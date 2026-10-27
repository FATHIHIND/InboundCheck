"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { resolveWizardRoute } from "@/lib/domain-selection";

export interface ReadinessCheckItem {
  check_id: string;
  title: string;
  status: "pass" | "warning" | "fail";
  impact: "critical" | "high" | "medium";
  finding: string;
  remediation: string;
  dns_record_snippet?: string | null;
}

export interface ShopifyReadinessData {
  domain: string;
  readiness_score: number;
  status: "ready" | "needs_attention" | "critical";
  passed_checks: number;
  total_checks: number;
  checks: ReadinessCheckItem[];
  evaluated_at: string;
  can_activate_zero_spam: boolean;
  summary: string;
}

export interface ZeroSpamWizardProps {
  isOpen: boolean;
  onClose: () => void;
  domain?: string;
  onSuccess?: () => void;
}

/**
 * @deprecated Consolidated into the dedicated `/dashboard/wizard` full-page route.
 * This compatibility component prevents breaking imports and seamlessly transitions
 * any legacy modal invocations to the centralized `/dashboard/wizard` route.
 */
export const ZeroSpamWizardModal: React.FC<ZeroSpamWizardProps> = ({
  isOpen,
  onClose,
  domain,
}) => {
  const router = useRouter();

  useEffect(() => {
    if (isOpen) {
      const destination = resolveWizardRoute({ domain });
      router.push(destination);
      onClose();
    }
  }, [isOpen, domain, router, onClose]);

  return null;
};

export default ZeroSpamWizardModal;
