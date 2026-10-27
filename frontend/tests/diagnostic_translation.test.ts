import test from "node:test";
import assert from "node:assert/strict";
import {
  translateDiagnosticIssue,
  translateRblStatus,
  getSeverityBadgeLabel,
} from "../src/lib/diagnostic-translator";
import type { RawDiagnosticIssue } from "../src/lib/diagnostic-translator";

test("Group 28: Merchant Jargon Translation & Plain-English Diagnostic Remediation", async (t) => {
  await t.test("1. DMARC translations provide 5 pillars and avoid raw technical jargon", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "dmarc-missing",
      category: "DMARC",
      severity: "critical",
      title: "DMARC Policy Record Missing",
      description:
        "Your domain lacks a valid DMARC record. Both Google and Yahoo reject unauthenticated emails from domains without DMARC.",
      impact:
        "High risk of rejection and inability to protect domain from email spoofing and phishing.",
      recommendation:
        "Publish a TXT record at `_dmarc.store.com` with at least `p=none`.",
      evidence: "No DMARC TXT record detected at `_dmarc.store.com`",
      remediation_record: {
        record_type: "TXT",
        host: "_dmarc.store.com",
        value: "v=DMARC1; p=quarantine; pct=100; rua=mailto:dmarc-reports@store.com;",
        ttl: 3600,
      },
    };

    const diag = translateDiagnosticIssue(rawIssue, {
      domain: "store.com",
      hasCloudflare: true,
    });

    assert.equal(diag.id, "dmarc-missing");
    assert.equal(diag.category, "DMARC");
    assert.equal(diag.badgeLabel, "Action Required");
    assert.match(diag.whatWeFound, /No DMARC protection record was found/i);
    assert.match(diag.whyItMatters, /Gmail and Yahoo.*may reject or send to spam/i);
    assert.match(diag.businessImpact, /order confirmations, shipping updates, or password resets/i);
    assert.match(diag.nextAction, /Publish a DMARC policy record/i);
    assert.equal(diag.fixMethod, "automated");
    assert.equal(diag.fixMethodLabel, "1-Click Auto-Fix Available");
    assert.match(diag.verificationStep, /Verify Records Live/i);

    // Verify technical details preservation (zero data loss)
    assert.equal(diag.technicalDetails.rawId, "dmarc-missing");
    assert.equal(diag.technicalDetails.rawTitle, "DMARC Policy Record Missing");
    assert.equal(
      diag.technicalDetails.evidence,
      "No DMARC TXT record detected at `_dmarc.store.com`"
    );
    assert.deepEqual(diag.technicalDetails.remediationRecord, rawIssue.remediation_record);
  });

  await t.test("2. DMARC p=none warning explains monitoring posture and upgrade path", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "dmarc-policy-none",
      category: "DMARC",
      severity: "warning",
      title: "DMARC Policy is Monitoring Only (p=none)",
      description: "Your DMARC policy is set to `none`.",
    };

    const diag = translateDiagnosticIssue(rawIssue, { hasCloudflare: false });

    assert.equal(diag.badgeLabel, "Attention");
    assert.match(diag.whatWeFound, /monitoring-only mode/i);
    assert.match(diag.whyItMatters, /not instructed to block or filter spoofed messages/i);
    assert.match(diag.nextAction, /upgrade your policy to p=quarantine or p=reject/i);
    assert.equal(diag.fixMethod, "manual");
    assert.equal(diag.fixMethodLabel, "Manual DNS Update Required");
  });

  await t.test("3. SPF PermError / multiple records translation instructs merge", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "spf-multiple-records",
      category: "SPF",
      severity: "critical",
      title: "Multiple SPF TXT Records Detected (RFC PermError)",
      description: "RFC 7208 specifies that a domain MUST NOT have multiple SPF TXT records.",
    };

    const diag = translateDiagnosticIssue(rawIssue);

    assert.equal(diag.badgeLabel, "Action Required");
    assert.match(diag.whatWeFound, /Multiple separate SPF records were detected/i);
    assert.match(diag.whyItMatters, /triggers a permanent error \(PermError\)/i);
    assert.match(diag.nextAction, /SPF Merge Engine/i);
    assert.equal(diag.fixMethod, "manual");
    assert.equal(diag.fixMethodLabel, "SPF Merge Required");
  });

  await t.test("4. SPF lookup limit exceeded explains 10-lookup barrier simply", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "spf-lookup-limit-exceeded",
      category: "SPF",
      severity: "critical",
      title: "SPF DNS Lookup Limit Exceeded (14/10 max)",
      description: "Your SPF record requires ~14 DNS lookups.",
    };

    const diag = translateDiagnosticIssue(rawIssue);

    assert.match(diag.whatWeFound, /more than 10 DNS lookups/i);
    assert.match(diag.whyItMatters, /RFC 7208 enforces a strict 10-lookup barrier/i);
    assert.match(diag.nextAction, /Simplify your SPF record/i);
  });

  await t.test("5. Dangerous +all SPF finding conveys critical security alert", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "spf-dangerous-all",
      category: "SPF",
      severity: "critical",
      title: "SPF Record Uses Dangerous '+all' Mechanism",
    };

    const diag = translateDiagnosticIssue(rawIssue, { hasCloudflare: true });

    assert.match(diag.whatWeFound, /authorizes every server on the internet/i);
    assert.match(diag.whyItMatters, /forge emails appearing to come from your store/i);
    assert.match(diag.businessImpact, /risk of fraud, customer deception, phishing attacks/i);
    assert.match(diag.nextAction, /replace '\+all' with '~all'/i);
  });

  await t.test("6. DKIM missing selectors translates into actionable instructions", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "dkim-missing-selectors",
      category: "DKIM",
      severity: "critical",
      title: "No Active DKIM Selectors Discovered",
    };

    const diag = translateDiagnosticIssue(rawIssue);

    assert.match(diag.whatWeFound, /could not find active cryptographic DKIM keys/i);
    assert.match(diag.whyItMatters, /receiving mail servers cannot verify that messages actually came from your domain/i);
    assert.match(diag.nextAction, /Shopify Admin .* or your email marketing app/i);
  });

  await t.test("7. Missing MX records and private IP translations explain mail routing impact", () => {
    const missingMx: RawDiagnosticIssue = {
      id: "mx-missing",
      category: "MX",
      severity: "critical",
    };
    const diagMissing = translateDiagnosticIssue(missingMx);
    assert.match(diagMissing.whatWeFound, /No Mail Exchanger \(MX\) records were found/i);
    assert.match(diagMissing.whyItMatters, /cannot receive inbound emails or delivery bounce notifications/i);

    const privateIpMx: RawDiagnosticIssue = {
      id: "mx-private-ip",
      category: "INFRASTRUCTURE",
      severity: "critical",
    };
    const diagPrivate = translateDiagnosticIssue(privateIpMx);
    assert.match(diagPrivate.whatWeFound, /resolves to a private or internal IP address/i);
    assert.match(diagPrivate.whyItMatters, /cannot be reached over the public internet/i);
  });

  await t.test("8. Apex CNAME conflict finding explains why email and web clash", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "dns-apex-cname",
      category: "DNS",
      severity: "critical",
    };

    const diag = translateDiagnosticIssue(rawIssue);

    assert.match(diag.whatWeFound, /CNAME record was detected at the root \(apex\)/i);
    assert.match(diag.whyItMatters, /other records \(like MX, TXT, and NS\) cannot reliably coexist/i);
    assert.match(diag.nextAction, /Replace the apex CNAME with standard A records/i);
  });

  await t.test("9. Blacklist listed finding prioritizes urgent merchant delisting", () => {
    const rawIssue: RawDiagnosticIssue = {
      id: "rbl-listed",
      category: "REPUTATION",
      severity: "critical",
    };

    const diag = translateDiagnosticIssue(rawIssue);

    assert.match(diag.whatWeFound, /listed on one or more spam blocklists/i);
    assert.match(diag.businessImpact, /transactional receipts, tracking updates, and marketing emails may fail to reach customers/i);
    assert.match(diag.nextAction, /Blacklist Radar/i);
    assert.equal(diag.fixMethod, "investigate");
  });

  await t.test("10. Unknown or future diagnostic IDs fall back gracefully with zero data loss", () => {
    const unknownIssue: RawDiagnosticIssue = {
      id: "future-custom-check-999",
      category: "SECURITY",
      severity: "warning",
      title: "MTA-STS Strict Mode Recommended",
      description: "Custom diagnostic telemetry finding.",
      evidence: "mta-sts.store.com returned status 404",
      remediation_record: {
        record_type: "TXT",
        host: "_mta-sts.store.com",
        value: "v=STSv1; id=20261027;",
      },
    };

    const diag = translateDiagnosticIssue(unknownIssue, { hasCloudflare: false });

    assert.equal(diag.id, "future-custom-check-999");
    assert.equal(diag.category, "SECURITY");
    assert.equal(diag.badgeLabel, "Attention");
    assert.equal(diag.whatWeFound, "MTA-STS Strict Mode Recommended");
    assert.equal(diag.technicalDetails.rawId, "future-custom-check-999");
    assert.equal(diag.technicalDetails.evidence, "mta-sts.store.com returned status 404");
    assert.equal(diag.fixMethod, "manual");
  });

  await t.test("11. Incomplete or missing diagnostic fields handle edge cases safely", () => {
    const incompleteIssue: RawDiagnosticIssue = {
      id: "incomplete-issue",
      category: "",
      severity: "",
    };

    const diag = translateDiagnosticIssue(incompleteIssue);

    assert.equal(diag.category, "DNS");
    assert.equal(diag.badgeLabel, "Informational");
    assert.ok(diag.whatWeFound.length > 0);
    assert.ok(diag.whyItMatters.length > 0);
    assert.ok(diag.nextAction.length > 0);
    assert.equal(diag.technicalDetails.evidence, null);
    assert.equal(diag.technicalDetails.remediationRecord, null);
  });

  await t.test("12. translateRblStatus produces clear guidance across all 5 states", () => {
    // 1. Listed
    const listed = translateRblStatus("listed", "Spamhaus ZEN", ["127.0.0.2"]);
    assert.equal(listed.statusLabel, "Listed on Blocklist");
    assert.equal(listed.isUrgent, true);
    assert.match(listed.whatWeFound, /Spamhaus ZEN blocklist \(Code: 127\.0\.0\.2\)/);
    assert.match(listed.nextAction, /official delisting portal/);

    // 2. Clean
    const clean = translateRblStatus("clean", "Barracuda BRBL");
    assert.equal(clean.statusLabel, "Clean (No Listing)");
    assert.equal(clean.isUrgent, false);
    assert.match(clean.whatWeFound, /No active spam listings detected on Barracuda BRBL/);

    // 3. Timeout
    const timeout = translateRblStatus("timeout", "SpamCop");
    assert.equal(timeout.statusLabel, "Query Timed Out");
    assert.equal(timeout.isUrgent, false);
    assert.match(timeout.whyItMatters, /temporary network issue or volume limitation/);

    // 4. Unknown
    const unknown = translateRblStatus("unknown", "Invaluement");
    assert.equal(unknown.statusLabel, "Inconclusive Response");
    assert.equal(unknown.isUrgent, false);

    // 5. Error
    const error = translateRblStatus("error", "UCEPROTECT");
    assert.equal(error.statusLabel, "Resolver Notice");
    assert.equal(error.isUrgent, false);
  });

  await t.test("13. getSeverityBadgeLabel formats all severities accurately", () => {
    assert.equal(getSeverityBadgeLabel("critical"), "Action Required");
    assert.equal(getSeverityBadgeLabel("warning"), "Attention");
    assert.equal(getSeverityBadgeLabel("info"), "Informational");
    assert.equal(getSeverityBadgeLabel("optimal"), "Optimal");
    assert.equal(getSeverityBadgeLabel("unknown-level"), "Diagnostic Notice");
  });
});
