"""
InboundCheck - DNS Record Generator
===================================
Generates copy-paste ready DNS records for eCommerce domain authentication.
Supports Shopify, Google Workspace, Microsoft 365, Klaviyo, SendGrid, and custom setups.
"""

from typing import List, Dict, Any, Optional
from app.schemas.dns import DNSRecordFix, GenerateRecordRequest


class DNSRecordGenerator:
    """
    Constructs compliant DNS records tailored for eCommerce tech stacks.
    """

    @staticmethod
    def generate_spf_record(
        domain: str,
        include_shopify: bool = True,
        include_google: bool = False,
        include_microsoft: bool = False,
        include_klaviyo: bool = False,
        include_sendgrid: bool = False,
        custom_includes: Optional[List[str]] = None,
        qualifier: str = "~all"
    ) -> DNSRecordFix:
        """Construct merged SPF TXT record."""
        mechanisms = []

        if include_shopify:
            mechanisms.append("include:shops.shopify.com")
        if include_google:
            mechanisms.append("include:_spf.google.com")
        if include_microsoft:
            mechanisms.append("include:spf.protection.outlook.com")
        if include_klaviyo:
            mechanisms.append("include:klaviyomail.com")
        if include_sendgrid:
            mechanisms.append("include:sendgrid.net")

        if custom_includes:
            for inc in custom_includes:
                clean_inc = inc.strip()
                if clean_inc and f"include:{clean_inc}" not in mechanisms:
                    mechanisms.append(f"include:{clean_inc}")

        spf_value = f"v=spf1 {' '.join(mechanisms)} {qualifier}".strip()

        return DNSRecordFix(
            record_type="TXT",
            host="@",
            value=spf_value,
            ttl=3600,
            category="SPF",
            rationale="Authorizes your chosen eCommerce and email providers to send transactional mail without SPF soft/hard failures."
        )

    @staticmethod
    def generate_dmarc_record(
        domain: str,
        policy: str = "quarantine",
        report_email: Optional[str] = None,
        pct: int = 100,
        aspf: str = "r",
        adkim: str = "r"
    ) -> DNSRecordFix:
        """Construct standard DMARC TXT record."""
        rua_addr = report_email if report_email else f"dmarc-reports@{domain}"
        dmarc_val = f"v=DMARC1; p={policy}; pct={pct}; rua=mailto:{rua_addr}; aspf={aspf}; adkim={adkim};"

        return DNSRecordFix(
            record_type="TXT",
            host=f"_dmarc",
            value=dmarc_val,
            ttl=3600,
            category="DMARC",
            rationale=f"Sets DMARC policy to {policy} and sends daily aggregate failure reports to {rua_addr}."
        )

    @staticmethod
    def generate_shopify_dkim_records(domain: str) -> List[DNSRecordFix]:
        """Construct CNAME records required by Shopify for domain authentication."""
        return [
            DNSRecordFix(
                record_type="CNAME",
                host="shopify._domainkey",
                value="dkim1.custom.shopify.com.",
                ttl=3600,
                category="DKIM",
                rationale="Shopify primary DKIM signing key."
            ),
            DNSRecordFix(
                record_type="CNAME",
                host="shopify2._domainkey",
                value="dkim2.custom.shopify.com.",
                ttl=3600,
                category="DKIM",
                rationale="Shopify secondary DKIM key for automatic key rotation."
            ),
            DNSRecordFix(
                record_type="CNAME",
                host="shopify3._domainkey",
                value="dkim3.custom.shopify.com.",
                ttl=3600,
                category="DKIM",
                rationale="Shopify tertiary DKIM key for uninterrupted email verification."
            )
        ]

    @staticmethod
    def generate_full_stack_records(request: GenerateRecordRequest) -> List[DNSRecordFix]:
        """Generate a complete set of tailored records based on user request."""
        records: List[DNSRecordFix] = []

        # 1. SPF
        spf_rec = DNSRecordGenerator.generate_spf_record(
            domain=request.domain,
            include_shopify=request.include_shopify,
            include_google=request.include_google,
            include_microsoft=request.include_microsoft,
            include_klaviyo=request.include_klaviyo,
            include_sendgrid=request.include_sendgrid
        )
        records.append(spf_rec)

        # 2. DMARC
        dmarc_rec = DNSRecordGenerator.generate_dmarc_record(
            domain=request.domain,
            policy=request.dmarc_policy,
            report_email=request.dmarc_report_email
        )
        records.append(dmarc_rec)

        # 3. Shopify DKIM (if requested)
        if request.include_shopify:
            records.extend(DNSRecordGenerator.generate_shopify_dkim_records(request.domain))

        return records
