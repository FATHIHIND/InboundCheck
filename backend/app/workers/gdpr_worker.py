"""One bounded GDPR batch. No imports connect, no CLI/loop or deployment wiring.

SQL owns tenant scope, atomic execution, lease expiry, retries and completion.
"""
from __future__ import annotations

from uuid import uuid4
from typing import Any

from app.services.privacy.repository import PrivacyAcceptanceError, call_rpc, require_uuid


class GDPRWorker:
    def __init__(self, client: Any, *, worker_id: str | None = None):
        if client is None:
            raise PrivacyAcceptanceError("Privacy persistence unavailable")
        self.client = client
        self.worker_id = require_uuid(worker_id or str(uuid4()))

    def run_once(self, *, limit: int = 1, lease_seconds: int = 120) -> dict:
        # Small default batch: each lease starts at claim, not at processing time.
        if type(limit) is not int or not 1 <= limit <= 10 or type(lease_seconds) is not int or not 30 <= lease_seconds <= 900:
            raise ValueError("Invalid privacy worker bounds")
        jobs = call_rpc(self.client, "claim_privacy_jobs", {
            "p_worker_id": self.worker_id, "p_limit": limit,
            "p_lease_seconds": lease_seconds,
        })
        if not isinstance(jobs, list) or len(jobs) > limit:
            raise PrivacyAcceptanceError("Invalid privacy claim receipt")
        summary = {"claimed": len(jobs), "completed": 0, "requires_manual_review": 0, "retry_or_failed": 0}
        for job in jobs:
            if not isinstance(job, dict):
                raise PrivacyAcceptanceError("Invalid privacy claim receipt")
            job_id = require_uuid(job.get("id"))
            if job.get("claimed_by") != self.worker_id or job.get("state") != "processing":
                raise PrivacyAcceptanceError("Invalid privacy claim ownership")
            try:
                result = call_rpc(self.client, "execute_privacy_job", {
                    "p_job_id": job_id, "p_worker_id": self.worker_id,
                })
                if not isinstance(result, dict) or result.get("job_id") != job_id or result.get("status") not in {"completed", "requires_manual_review"}:
                    raise PrivacyAcceptanceError("Invalid privacy execution receipt")
                # A count receipt is not a legitimate subject-access export.
                if job.get("kind") == "customers/data_request" and result["status"] == "completed":
                    raise PrivacyAcceptanceError("Invalid privacy export completion")
                summary[result["status"]] += 1
            except PrivacyAcceptanceError:
                # If SQL committed but transport response was lost, failure RPC must
                # return existing terminal result or reject expired lease; never undo.
                failure = call_rpc(self.client, "fail_privacy_job", {
                    "p_job_id": job_id, "p_worker_id": self.worker_id,
                    "p_error_code": "execution_unconfirmed",
                })
                if not isinstance(failure, dict) or failure.get("job_id") != job_id or failure.get("status") not in {"queued", "failed", "completed", "requires_manual_review"}:
                    raise PrivacyAcceptanceError("Invalid privacy failure receipt")
                summary["retry_or_failed"] += 1
        return summary
