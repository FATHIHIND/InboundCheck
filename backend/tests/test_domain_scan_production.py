"""
InboundCheck - Production-Ready Domain Scan End-to-End Test Suite
==================================================================
Tests end-to-end domain scanning workflow:
- Normalization (URLs, paths, queries, ports, www prefix)
- Authentication enforcement & unauthorized rejection
- Input validation & SSRF protection
- DNS records, mail infrastructure, and email authentication checks
- Checks summary and risk level computation
- Audit persistence in Supabase / memory store
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.supabase_client import supabase_service
from tests.conftest import auth_headers


def test_scan_unauthorized_rejected():
    """Unauthenticated scan request must fail closed with 401."""
    client = TestClient(app)
    res = client.post("/api/v1/dns/audit", json={"domain": "example.com"})
    assert res.status_code == 401
    assert "Authentication required" in res.json().get("detail", "")


def test_scan_invalid_domain_graceful_error():
    """Invalid domain, SSRF, or malformed inputs must return 400 with actionable error (not 500)."""
    client = TestClient(app, headers=auth_headers("test-scan-user-1"))

    # Empty string
    res = client.post("/api/v1/dns/audit", json={"domain": ""})
    assert res.status_code in [400, 422]

    # Localhost / internal
    res_ssrf = client.post("/api/v1/dns/audit", json={"domain": "http://localhost:8000"})
    assert res_ssrf.status_code == 400
    assert "SSRF" in res_ssrf.json().get("detail", "") or "restricted" in res_ssrf.json().get("detail", "")

    # IP address
    res_ip = client.post("/api/v1/dns/audit", json={"domain": "127.0.0.1"})
    assert res_ip.status_code == 400

    # Invalid characters
    res_bad = client.post("/api/v1/dns/audit", json={"domain": "invalid_domain^^^.com"})
    assert res_bad.status_code == 400


def test_scan_workflow_authenticated_and_normalized():
    """Authenticated user submits full URL; system normalizes, scans, persists, and returns complete report."""
    user_id = "00000000-0000-0000-0000-000000000001"
    client = TestClient(app, headers=auth_headers(user_id))

    # Input has scheme, port, path, and query params
    raw_input = "https://example.com:443/checkout?ref=campaign#intro"
    res = client.post(
        "/api/v1/dns/audit",
        json={
            "domain": raw_input,
            "include_reputation": False  # Fast unit test mode
        }
    )
    assert res.status_code == 200
    data = res.json()

    # 1. Domain must be normalized to clean apex
    assert data["domain"] == "example.com"

    # 2. Overall health and status
    assert 0 <= data["health_score"] <= 100
    assert data["status"] in ["optimal", "warning", "critical"]
    assert data["risk_level"] in ["Low Risk", "Medium Risk", "High Risk", "Critical Risk"]

    # 3. Checks summary
    checks = data.get("checks_summary")
    assert checks is not None
    assert checks["total_checks"] > 0

    # 4. Diagnostic summary must include core DNS and Mail Infrastructure
    summary = data["summary"]
    assert "mx" in summary
    assert "spf" in summary
    assert "dkim" in summary
    assert "dmarc" in summary
    assert "dns_records" in summary
    assert "mail_infrastructure" in summary

    # 5. Issues and fixes
    assert isinstance(data["issues"], list)
    assert isinstance(data["fixes"], list)

    # 6. Audit persistence verified in database or in-memory fallback
    history = supabase_service.get_audit_history(user_id=user_id, domain_name="example.com", limit=5)
    logs = supabase_service._in_memory_logs.get("example.com", [])
    assert len(history) > 0 or len(logs) > 0
    record = history[0] if history else logs[0]
    assert record["domain_name"] == "example.com"
    assert record["health_score"] == data["health_score"]

    # 7. Checks summary must support both count aliases for frontend backward-compatibility
    assert "passed" in checks and "passed_count" in checks
    assert "warnings" in checks and "warning_count" in checks
    assert "failures" in checks and "failure_count" in checks
    assert "unavailable" in checks and "unavailable_count" in checks
    assert checks["passed"] == checks["passed_count"]

    # 8. Mail infrastructure summary must include mx_host_count and mx_records list
    mail_infra = summary["mail_infrastructure"]
    assert "mx_host_count" in mail_infra
    assert "mx_records" in mail_infra
    assert isinstance(mail_infra["mx_records"], list)

    # 9. Issues must have message populated
    for issue in data["issues"]:
        assert issue.get("message") is not None
        assert len(issue["message"]) > 0


def test_rbl_scan_with_normalized_input():
    """RBL scan endpoint accepts messy domain/URL and normalizes cleanly."""
    client = TestClient(app, headers=auth_headers("test-scan-user-2"))

    res = client.post(
        "/api/v1/dns/rbl-scan",
        json={"domain": "http://www.example.com/some/path"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["domain"] == "example.com"
    assert data["rbl_total_count"] == 10
    assert data["overall_status"] in ["clean", "listed", "partial", "unavailable"]


def test_scan_history_endpoint_and_isolation():
    """GET /api/v1/dns/history must return persisted scans for current user only."""
    user_a = "11111111-1111-1111-1111-111111111111"
    user_b = "22222222-2222-2222-2222-222222222222"

    client_a = TestClient(app, headers=auth_headers(user_a))
    client_b = TestClient(app, headers=auth_headers(user_b))

    # User A performs a scan on example.com
    res_a = client_a.post("/api/v1/dns/audit", json={"domain": "example.com", "include_reputation": False})
    assert res_a.status_code == 200

    # User A retrieves history
    hist_a = client_a.get("/api/v1/dns/history?domain=example.com")
    assert hist_a.status_code == 200
    items_a = hist_a.json()
    assert isinstance(items_a, list)
    assert len(items_a) >= 1
    assert items_a[0]["domain_name"] == "example.com"

    # User B retrieves history for example.com - must NOT see User A's audits
    hist_b = client_b.get("/api/v1/dns/history?domain=example.com")
    assert hist_b.status_code == 200
    items_b = hist_b.json()
    assert isinstance(items_b, list)
    # User B has not scanned example.com, so it must be empty
    assert len(items_b) == 0

    # History endpoint requires authentication
    unauth_client = TestClient(app)
    res_unauth = unauth_client.get("/api/v1/dns/history")
    assert res_unauth.status_code == 401
