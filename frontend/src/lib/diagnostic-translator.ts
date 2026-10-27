/**
 * InboundCheck — Merchant Diagnostic Translation & Plain-English Engine
 * Translates low-level RFC/DNS/RBL technical errors and findings into actionable,
 * plain-English explanations for non-technical Shopify merchants.
 */

export interface RawDiagnosticIssue {
  id: string;
  category: string;
  severity: "critical" | "warning" | "info" | "optimal" | string;
  title?: string;
  description?: string;
  message?: string;
  impact?: string;
  recommendation?: string;
  evidence?: string | null;
  remediation_record?: {
    record_type: string;
    host: string;
    value: string;
    ttl?: string | number;
  } | null;
}

export type FixMethodType = "automated" | "manual" | "investigate";

export interface PlainEnglishDiagnostic {
  id: string;
  category: string;
  severity: "critical" | "warning" | "info" | "optimal" | string;
  badgeLabel: string;

  // 5 Pillars of the Merchant Diagnostic Contract
  whatWeFound: string;
  whyItMatters: string;
  businessImpact: string;
  nextAction: string;
  fixMethod: FixMethodType;
  fixMethodLabel: string;
  verificationStep: string;

  // Technical details for advanced users & support
  technicalDetails: {
    rawId: string;
    rawTitle: string;
    rawDescription: string;
    evidence: string | null;
    category: string;
    remediationRecord: {
      record_type: string;
      host: string;
      value: string;
      ttl?: string | number;
    } | null;
  };
}

export interface TranslationContext {
  domain?: string;
  hasCloudflare?: boolean;
  hasGoDaddy?: boolean;
}

/**
 * Authoritative dictionary mapping known issue IDs to merchant-centric plain-English guidance.
 */
const KNOWN_TRANSLATIONS: Record<
  string,
  (issue: RawDiagnosticIssue, ctx: TranslationContext) => {
    whatWeFound: string;
    whyItMatters: string;
    businessImpact: string;
    nextAction: string;
    fixMethod: FixMethodType;
    fixMethodLabel: string;
    verificationStep: string;
  }
> = {
  // DMARC Findings
  "dmarc-missing": (_issue, ctx) => ({
    whatWeFound: "No DMARC protection record was found in your domain's DNS settings.",
    whyItMatters:
      "Major email providers (including Gmail and Yahoo) may reject or send to spam order confirmations and customer receipts sent from domains without DMARC.",
    businessImpact:
      "Customers may not receive order confirmations, shipping updates, or password resets, which can lead to increased support requests or chargebacks.",
    nextAction:
      "Publish a DMARC policy record on your DNS zone. Starting with a monitoring policy (p=none) or quarantine policy (p=quarantine) protects your sending identity.",
    fixMethod: ctx.hasCloudflare ? "automated" : "manual",
    fixMethodLabel: ctx.hasCloudflare
      ? "1-Click Auto-Fix Available"
      : "Manual DNS Update Required",
    verificationStep:
      "After adding the record to your DNS manager, click 'Verify Records Live' to confirm receiving servers can detect your policy.",
  }),

  "dmarc-policy-none": (_issue, ctx) => ({
    whatWeFound:
      "Your DMARC record is in monitoring-only mode (p=none).",
    whyItMatters:
      "Your domain collects authentication reports, but mailbox providers are not instructed to block or filter spoofed messages sent by unauthorized senders.",
    businessImpact:
      "Your store brand remains vulnerable to impersonation or phishing, which may harm your domain's sending reputation over time.",
    nextAction:
      "Confirm that your legitimate store senders (Shopify, Klaviyo, Google Workspace) are all signing emails, then upgrade your policy to p=quarantine or p=reject.",
    fixMethod: ctx.hasCloudflare ? "automated" : "manual",
    fixMethodLabel: ctx.hasCloudflare
      ? "1-Click Auto-Fix Available"
      : "Manual DNS Update Required",
    verificationStep:
      "Update your DNS record to p=quarantine and re-run the inspection to verify the strengthened posture.",
  }),

  "dmarc-no-rua": () => ({
    whatWeFound:
      "Your DMARC record does not specify an aggregate reporting email address (rua).",
    whyItMatters:
      "Receiving mailbox providers cannot deliver daily aggregate reports showing which servers are attempting to send email using your domain.",
    businessImpact:
      "You have no visibility into delivery failures, authentication misconfigurations, or potential spoofing attempts.",
    nextAction:
      "Add a reporting address (for example: rua=mailto:dmarc-reports@yourdomain.com) into your DMARC TXT record.",
    fixMethod: "manual",
    fixMethodLabel: "Manual DNS Update Required",
    verificationStep:
      "Save the updated record and re-audit to verify that daily reporting is active.",
  }),

  "dmarc-pct-suboptimal": (issue) => ({
    whatWeFound:
      "Your DMARC policy applies to only a fraction of outgoing messages.",
    whyItMatters:
      "A partial percentage setting means some unauthorized messages could bypass enforcement while legitimate messages receive inconsistent handling.",
    businessImpact:
      "Protection against brand impersonation is incomplete, creating potential gaps in customer trust.",
    nextAction:
      "Change the percentage tag in your DMARC record to pct=100 so all messages are consistently evaluated.",
    fixMethod: "manual",
    fixMethodLabel: "Manual DNS Update Required",
    verificationStep:
      "Re-run the audit to confirm 100% enforcement is active.",
  }),

  // SPF Findings
  "spf-missing": (_issue, ctx) => ({
    whatWeFound: "No SPF record was found on your sending domain.",
    whyItMatters:
      "Receiving mailboxes cannot verify whether Shopify, Google Workspace, or your marketing tools are authorized to send email on your behalf.",
    businessImpact:
      "Order confirmations and transactional receipts are likely to be classified as spam or dropped entirely by Gmail, Yahoo, and Outlook.",
    nextAction:
      "Add an SPF TXT record containing authorization tags for all services that send email for your store.",
    fixMethod: ctx.hasCloudflare ? "automated" : "manual",
    fixMethodLabel: ctx.hasCloudflare
      ? "1-Click Auto-Fix Available"
      : "Manual DNS Update Required",
    verificationStep:
      "Publish the SPF TXT record, wait 5–10 minutes for DNS propagation, and click 'Verify Records Live'.",
  }),

  "spf-multiple-records": () => ({
    whatWeFound:
      "Multiple separate SPF records were detected in your domain settings.",
    whyItMatters:
      "Internet email standards (RFC 7208) allow only one SPF record per domain. Having more than one triggers a permanent error (PermError) that causes authentication to fail.",
    businessImpact:
      "Recipient mail servers may automatically mark store emails as fraudulent or route them directly to the spam folder.",
    nextAction:
      "Use our SPF Merge Engine to combine all authorized services into a single TXT record, then delete the duplicate records.",
    fixMethod: "manual",
    fixMethodLabel: "SPF Merge Required",
    verificationStep:
      "After replacing the multiple records with one merged record, re-run the inspection to ensure only one SPF record exists.",
  }),

  "spf-lookup-limit-exceeded": () => ({
    whatWeFound:
      "Your SPF record requires more than 10 DNS lookups to evaluate.",
    whyItMatters:
      "RFC 7208 enforces a strict 10-lookup barrier. When this limit is exceeded, mailbox servers produce a PermError and may reject or spam-box incoming mail.",
    businessImpact:
      "Transactional emails sent through services evaluated late in your lookup chain might never reach your customer's inbox.",
    nextAction:
      "Simplify your SPF record by removing services you no longer use, or use dedicated subdomains for third-party marketing tools.",
    fixMethod: "manual",
    fixMethodLabel: "Manual SPF Flattening Required",
    verificationStep:
      "Update your SPF record and re-audit to verify that the lookup counter is at 10 or fewer.",
  }),

  "spf-dangerous-all": (_issue, ctx) => ({
    whatWeFound:
      "Your SPF record ends with the '+all' directive, which authorizes every server on the internet to send mail for your domain.",
    whyItMatters:
      "Anyone in the world can forge emails appearing to come from your store, and recipient mailboxes will consider them authorized.",
    businessImpact:
      "Severe risk of fraud, customer deception, phishing attacks, and permanent domain reputation blacklisting.",
    nextAction:
      "Immediately replace '+all' with '~all' (softfail) or '-all' (hardfail) in your DNS manager.",
    fixMethod: ctx.hasCloudflare ? "automated" : "manual",
    fixMethodLabel: ctx.hasCloudflare
      ? "1-Click Auto-Fix Available"
      : "Manual DNS Update Required",
    verificationStep:
      "Save the corrected record and immediately re-audit your domain.",
  }),

  "spf-softfail-notice": () => ({
    whatWeFound:
      "Your SPF record uses softfail (~all), which is the recommended configuration for Shopify and DTC brands.",
    whyItMatters:
      "When paired with an active DMARC policy, softfail allows legitimate multi-vendor transactional senders to deliver cleanly while spoofers are handled safely.",
    businessImpact:
      "Healthy deliverability foundation aligned with 2024 Google and Yahoo mailbox standards.",
    nextAction:
      "No changes needed at this time. Maintain your list of authorized sending tools as your store evolves.",
    fixMethod: "manual",
    fixMethodLabel: "Configuration Optimal",
    verificationStep:
      "Continue monitoring through scheduled domain audits.",
  }),

  "spf-neutral-all": () => ({
    whatWeFound:
      "Your SPF record terminates with the neutral qualifier '?all'.",
    whyItMatters:
      "The neutral qualifier takes no stance on unauthorized senders, providing less certainty to recipient spam filters.",
    businessImpact:
      "Spam filters may scrutinize your messages more strictly, potentially lowering delivery rates during high-volume sales periods.",
    nextAction:
      "Change '?all' to '~all' at the end of your SPF record for stronger deliverability alignment.",
    fixMethod: "manual",
    fixMethodLabel: "Manual DNS Update Required",
    verificationStep:
      "Save the change and re-audit to confirm the '~all' qualifier.",
  }),

  // DKIM Findings
  "dkim-missing-selectors": () => ({
    whatWeFound:
      "We could not find active cryptographic DKIM keys for your expected email selectors.",
    whyItMatters:
      "Without DKIM, receiving mail servers cannot verify that messages actually came from your domain and were not tampered with in transit.",
    businessImpact:
      "Emails may fail DMARC alignment checks, causing Gmail, Yahoo, and Outlook to route order notifications to the spam folder.",
    nextAction:
      "Open your Shopify Admin (Settings > Notifications) or your email marketing app, locate your unique DKIM CNAME records, and publish them in your DNS manager.",
    fixMethod: "manual",
    fixMethodLabel: "Manual CNAME Publishing Required",
    verificationStep:
      "Once published, enter your selector into the Inspector and re-run the check to verify the cryptographic key responds.",
  }),

  "dkim-1024-bit-warning": () => ({
    whatWeFound:
      "Your domain is signing emails using a 1024-bit DKIM key.",
    whyItMatters:
      "1024-bit keys provide baseline authentication but are increasingly considered legacy compared to standard 2048-bit RSA encryption.",
    businessImpact:
      "Some corporate, government, or educational mail filters apply slight reputation penalties to 1024-bit keys.",
    nextAction:
      "When your email service provider supports 2048-bit DKIM keys, generate a new key pair and update your DNS records.",
    fixMethod: "investigate",
    fixMethodLabel: "Investigate with Mail Provider",
    verificationStep:
      "After updating your provider's DKIM settings, re-audit to confirm 2048-bit key detection.",
  }),

  // MX Infrastructure Findings
  "mx-missing": () => ({
    whatWeFound:
      "No Mail Exchanger (MX) records were found for your domain.",
    whyItMatters:
      "Your domain cannot receive inbound emails or delivery bounce notifications from recipient servers.",
    businessImpact:
      "Many receiving mail servers consider sending-only domains without MX records suspicious, which can increase spam filtering.",
    nextAction:
      "Add MX records pointing to your business email provider (such as Google Workspace, Microsoft 365, or Zoho).",
    fixMethod: "manual",
    fixMethodLabel: "Manual MX Setup Required",
    verificationStep:
      "Save the MX records in your DNS manager and re-audit to confirm inbound mail routing.",
  }),

  "mx-no-redundancy": () => ({
    whatWeFound:
      "Only a single MX mail server is configured for your domain.",
    whyItMatters:
      "If that mail server experiences temporary downtime, incoming customer replies and bounce notices cannot be received.",
    businessImpact:
      "Possible missed customer messages or delivery reports during hosting outages.",
    nextAction:
      "Add a secondary backup MX record provided by your email hosting service.",
    fixMethod: "manual",
    fixMethodLabel: "Optional Redundancy Recommended",
    verificationStep:
      "Re-audit to confirm both primary and secondary MX servers are detected.",
  }),

  "mx-private-ip": () => ({
    whatWeFound:
      "One or more of your MX mail servers resolves to a private or internal IP address.",
    whyItMatters:
      "Private IP addresses (such as 10.x.x.x or 192.168.x.x) cannot be reached over the public internet.",
    businessImpact:
      "All inbound customer replies and bounce notifications will fail completely.",
    nextAction:
      "Update your MX records to point to publicly accessible mail servers provided by your email host.",
    fixMethod: "manual",
    fixMethodLabel: "Manual DNS Correction Required",
    verificationStep:
      "Re-audit to verify your mail server resolves to a public internet IP address.",
  }),

  "mx-points-to-cname": () => ({
    whatWeFound:
      "Your MX record points to a CNAME alias instead of a canonical server hostname.",
    whyItMatters:
      "RFC 2181 requires MX records to point directly to names with A or AAAA address records, not CNAME aliases.",
    businessImpact:
      "Strict mail transfer agents may delay message delivery or generate delivery warning logs.",
    nextAction:
      "Change the MX hostname to the direct mail server address specified by your email provider.",
    fixMethod: "manual",
    fixMethodLabel: "Manual DNS Update Required",
    verificationStep:
      "Re-audit after saving the canonical mail server hostname.",
  }),

  "mail-missing-ptr": () => ({
    whatWeFound:
      "One or more sending mail server IPs lack a reverse DNS (PTR) record.",
    whyItMatters:
      "Major email providers use reverse DNS to verify that the IP sending the email matches the domain in the headers.",
    businessImpact:
      "Emails sent directly from IPs without reverse DNS are frequently rejected or flagged as spam by Google and Yahoo.",
    nextAction:
      "Contact your email hosting provider or VPS host and ask them to configure a reverse DNS PTR record matching your mail domain.",
    fixMethod: "investigate",
    fixMethodLabel: "Contact Mail Host / ISP",
    verificationStep:
      "Re-run the audit once your mail provider confirms reverse DNS configuration.",
  }),

  // BIMI Findings
  "bimi-optional-bonus": () => ({
    whatWeFound:
      "No verified BIMI brand logo record is currently published.",
    whyItMatters:
      "BIMI is an optional visual enhancement that displays your verified store logo next to emails in supported inboxes like Apple Mail and Gmail.",
    businessImpact:
      "Not publishing BIMI will not harm your inbox placement; it simply means your brand logo is not displayed in the inbox preview.",
    nextAction:
      "If you have a registered trademark and a Verified Mark Certificate (VMC), you can publish a BIMI record to enhance brand visibility.",
    fixMethod: "manual",
    fixMethodLabel: "Optional Visual Enhancement",
    verificationStep:
      "If you publish a BIMI record, re-audit to verify that the SVG logo is reachable and compliant.",
  }),

  // Core DNS Findings
  "dns-apex-cname": () => ({
    whatWeFound:
      "A CNAME record was detected at the root (apex) of your domain.",
    whyItMatters:
      "DNS standards (RFC 1912) state that if a CNAME exists at the apex, other records (like MX, TXT, and NS) cannot reliably coexist.",
    businessImpact:
      "Can cause random, intermittent delivery failures for order receipts and temporary website downtime.",
    nextAction:
      "Replace the apex CNAME with standard A records pointing to your web host (for Shopify, point A to 23.227.38.65), or enable CNAME flattening at your DNS provider.",
    fixMethod: "manual",
    fixMethodLabel: "Manual DNS Architecture Fix",
    verificationStep:
      "Re-run the audit to verify that apex CNAME has been removed and A records resolve properly.",
  }),

  "dns-single-ns": () => ({
    whatWeFound:
      "Only one authoritative nameserver was found for your domain.",
    whyItMatters:
      "Reliable internet operations require at least two geographically separated nameservers to guarantee availability.",
    businessImpact:
      "If that single nameserver has an outage, all customer access to your store and email routing stops immediately.",
    nextAction:
      "Add a secondary nameserver through your domain registrar or switch to a provider with built-in redundancy (like Cloudflare).",
    fixMethod: "manual",
    fixMethodLabel: "Manual Registrar Update Required",
    verificationStep:
      "Re-audit to confirm that at least two independent nameservers respond.",
  }),

  "dns-missing-caa": (_issue, ctx) => ({
    whatWeFound:
      "No Certificate Authority Authorization (CAA) records were found.",
    whyItMatters:
      "CAA records specify which certificate authorities are allowed to issue SSL certificates for your store.",
    businessImpact:
      "This check does not affect email deliverability, but publishing CAA records protects your store from fraudulent certificate issuance.",
    nextAction:
      "Publish CAA records authorizing trusted certificate authorities like Let's Encrypt or DigiCert.",
    fixMethod: ctx.hasCloudflare ? "automated" : "manual",
    fixMethodLabel: ctx.hasCloudflare
      ? "1-Click Auto-Fix Available"
      : "Manual DNS Record Available",
    verificationStep:
      "Re-run the inspection to verify that your domain's CAA policy is detected.",
  }),

  "dns-no-ip": () => ({
    whatWeFound:
      "No A or AAAA address records were found for your root domain.",
    whyItMatters:
      "Your domain does not resolve to an active web server address and cannot handle mail systems that fall back to IP lookups.",
    businessImpact:
      "Customers cannot access your store website and fallback mail routing fails.",
    nextAction:
      "Add an A record pointing to your web hosting server or Shopify's IP (23.227.38.65).",
    fixMethod: "manual",
    fixMethodLabel: "Manual A Record Required",
    verificationStep:
      "Re-run the audit after saving the A record to confirm web and email resolution.",
  }),

  // Reputation & Blacklist Findings
  "rbl-listed": (issue) => ({
    whatWeFound:
      "Your domain or mail server IP is currently listed on one or more spam blocklists.",
    whyItMatters:
      "Recipient mail servers that consult these blocklists may reject your emails or automatically deliver them to the junk folder.",
    businessImpact:
      "Severe email deliverability drop: transactional receipts, tracking updates, and marketing emails may fail to reach customers.",
    nextAction:
      "Open Blacklist Radar, check the listed provider details, and follow their official delisting instructions to request removal.",
    fixMethod: "investigate",
    fixMethodLabel: "Delisting Request Required",
    verificationStep:
      "After submitting your delisting request, wait for the provider's confirmation and re-run Blacklist Radar to verify clean status.",
  }),

  "rbl-partial-notice": () => ({
    whatWeFound:
      "Your domain was verified clean on all responding blocklist databases.",
    whyItMatters:
      "No active listings were detected on authoritative reputation providers.",
    businessImpact:
      "Your sending reputation is in good standing across monitored anti-spam networks.",
    nextAction:
      "No remediation needed. Keep sending volume predictable and maintain clean subscriber lists.",
    fixMethod: "manual",
    fixMethodLabel: "Reputation Clean",
    verificationStep:
      "Run periodic reputation scans to monitor for unexpected listings.",
  }),

  "seed-spam-detected": () => ({
    whatWeFound:
      "Test messages sent from your domain were routed to the spam folder in inbox placement tests.",
    whyItMatters:
      "Mailbox filters flagged the content or sending headers of your test emails.",
    businessImpact:
      "Real customer order confirmations and promotional flows may be suffering similar spam placement.",
    nextAction:
      "Use the Template Optimizer to scan your email copy for trigger words, and ensure your SPF, DKIM, and DMARC records are fully aligned.",
    fixMethod: "investigate",
    fixMethodLabel: "Template & Header Optimization",
    verificationStep:
      "Re-test inbox placement after adjusting template copy and confirming DNS alignment.",
  }),
};

/**
 * Normalizes severity into a consistent display label.
 */
export function getSeverityBadgeLabel(severity: string): string {
  switch (severity?.toLowerCase()) {
    case "critical":
      return "Action Required";
    case "warning":
      return "Attention";
    case "info":
      return "Informational";
    case "optimal":
      return "Optimal";
    default:
      return "Diagnostic Notice";
  }
}

/**
 * Translates any raw diagnostic issue into a plain-English, merchant-centric diagnostic contract.
 * Guarantees zero data loss: technical details, RFC evidence, and raw fields are preserved.
 */
export function translateDiagnosticIssue(
  issue: RawDiagnosticIssue,
  context: TranslationContext = {}
): PlainEnglishDiagnostic {
  const normalizedId = (issue.id || "").toLowerCase().trim();
  const translator = KNOWN_TRANSLATIONS[normalizedId];

  const baseSeverity = issue.severity || "info";
  const badgeLabel = getSeverityBadgeLabel(baseSeverity);

  if (translator) {
    const translated = translator(issue, context);
    return {
      id: issue.id,
      category: issue.category || "DNS",
      severity: baseSeverity,
      badgeLabel,
      whatWeFound: translated.whatWeFound,
      whyItMatters: translated.whyItMatters,
      businessImpact: translated.businessImpact,
      nextAction: translated.nextAction,
      fixMethod: translated.fixMethod,
      fixMethodLabel: translated.fixMethodLabel,
      verificationStep: translated.verificationStep,
      technicalDetails: {
        rawId: issue.id,
        rawTitle: issue.title || issue.message || "Diagnostic Finding",
        rawDescription:
          issue.description || issue.message || "No detailed description provided.",
        evidence: issue.evidence || null,
        category: issue.category || "General",
        remediationRecord: issue.remediation_record || null,
      },
    };
  }

  // Graceful, neutral fallback for unknown or future diagnostic finding IDs
  const rawTitle = issue.title || issue.message || "Configuration Anomaly Detected";
  const rawDesc = issue.description || issue.message || "A diagnostic condition was identified on your domain.";

  const hasRemediation = !!issue.remediation_record;
  const fixMethod: FixMethodType = hasRemediation
    ? context.hasCloudflare
      ? "automated"
      : "manual"
    : "investigate";

  const fixMethodLabel = hasRemediation
    ? context.hasCloudflare
      ? "1-Click Auto-Fix Available"
      : "Manual DNS Update Required"
    : "Review with Technical Provider";

  return {
    id: issue.id,
    category: issue.category || "DNS",
    severity: baseSeverity,
    badgeLabel,
    whatWeFound: rawTitle,
    whyItMatters:
      rawDesc.length > 0 && !rawDesc.includes("RFC")
        ? rawDesc
        : "This setting may affect email authentication or delivery reliability under modern mailbox filtering standards.",
    businessImpact:
      issue.impact ||
      "Delivery performance or domain security may be reduced if mailbox filters flag this condition.",
    nextAction:
      issue.recommendation ||
      "Review your domain's DNS configuration and adjust records to match modern sender standards.",
    fixMethod,
    fixMethodLabel,
    verificationStep:
      "After adjusting your domain settings, re-run the inspection to verify that the condition has resolved.",
    technicalDetails: {
      rawId: issue.id,
      rawTitle,
      rawDescription: rawDesc,
      evidence: issue.evidence || null,
      category: issue.category || "General",
      remediationRecord: issue.remediation_record || null,
    },
  };
}

/**
 * Translates an RBL status code or record into plain-English merchant summary.
 */
export function translateRblStatus(
  status: "clean" | "listed" | "unknown" | "error" | "timeout" | string,
  providerName: string,
  responseCodes: string[] = []
): {
  statusLabel: string;
  whatWeFound: string;
  whyItMatters: string;
  businessImpact: string;
  nextAction: string;
  isUrgent: boolean;
} {
  const normStatus = (status || "").toLowerCase().trim();

  if (normStatus === "listed") {
    const codeNotice =
      responseCodes.length > 0 ? ` (Code: ${responseCodes.join(", ")})` : "";
    return {
      statusLabel: "Listed on Blocklist",
      whatWeFound: `Your domain or mail IP appears on the ${providerName} blocklist${codeNotice}.`,
      whyItMatters:
        "Recipient email providers subscribing to this blocklist may automatically reject your emails or route them to the spam folder.",
      businessImpact:
        "Severe deliverability risk: customer receipts, order confirmations, and promotional campaigns may fail to arrive.",
      nextAction:
        "Use the official delisting portal to review why the listing occurred and submit a removal request.",
      isUrgent: true,
    };
  }

  if (normStatus === "timeout") {
    return {
      statusLabel: "Query Timed Out",
      whatWeFound: `The query to ${providerName} timed out before receiving a response.`,
      whyItMatters:
        "This is usually a temporary network issue or volume limitation on the remote blocklist nameservers.",
      businessImpact:
        "No active listing was confirmed, but reputation status could not be verified in real time.",
      nextAction:
        "Re-run the scan in a few minutes, or use the direct lookup link to verify status manually.",
      isUrgent: false,
    };
  }

  if (normStatus === "error") {
    return {
      statusLabel: "Resolver Notice",
      whatWeFound: `The remote resolver for ${providerName} returned an unexpected error.`,
      whyItMatters:
        "The blocklist database nameservers could not complete the lookup request.",
      businessImpact:
        "Inconclusive scan for this specific list; other lists continue to monitor your reputation.",
      nextAction:
        "Check back later or visit the provider's direct lookup portal.",
      isUrgent: false,
    };
  }

  if (normStatus === "unknown") {
    return {
      statusLabel: "Inconclusive Response",
      whatWeFound: `The status on ${providerName} could not be determined conclusively from public resolvers.`,
      whyItMatters:
        "Some commercial blocklists restrict queries originating from shared public DNS resolvers.",
      businessImpact:
        "Your domain is not confirmed listed, but direct verification on the provider site is recommended.",
      nextAction:
        "Click the direct lookup link to confirm your reputation status directly on the provider's portal.",
      isUrgent: false,
    };
  }

  // Clean
  return {
    statusLabel: "Clean (No Listing)",
    whatWeFound: `No active spam listings detected on ${providerName}.`,
    whyItMatters:
      "Mailbox providers checking this database will not block your emails based on reputation.",
    businessImpact:
      "Supports primary inbox delivery for your store's transactional emails.",
    nextAction: "No action required. Your domain is in good standing.",
    isUrgent: false,
  };
}
