"""
InboundCheck - Dedicated Background Workers Package (Phase 4)
=============================================================
Provides standalone worker processes for:
- DNS & RBL deliverability audits via database leases (audit_worker).
- Omnichannel fallback incident dispatch (failover_worker).
- Master multi-worker runner CLI (runner).
"""
