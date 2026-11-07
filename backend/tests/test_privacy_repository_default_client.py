"""Regression test for BILL-13: the GDPR persistence path must use the real
Supabase client when no explicit client is injected.

Before the fix, ``_client_or_default`` read ``supabase_service.client``, an
attribute that does not exist (only ``_client`` does). The AttributeError was
swallowed by ``call_rpc`` and every production GDPR webhook returned 503.
Existing route tests patch ``accept_gdpr_request`` and never exercised this path.
"""
from types import SimpleNamespace

import pytest

from app.services.privacy import repository
from app.services.supabase_client import supabase_service


class _FakeRpc:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return SimpleNamespace(data=self._data, error=None)


class _FakeClient:
    def __init__(self, data):
        self.calls = []
        self._data = data

    def rpc(self, name, params):
        self.calls.append((name, params))
        return _FakeRpc(self._data)


def test_default_client_resolves_to_service_private_client(monkeypatch):
    fake = _FakeClient({"ok": True})
    monkeypatch.setattr(supabase_service, "_client", fake, raising=False)

    result = repository.call_rpc(repository._DEFAULT_CLIENT, "enqueue_privacy_job", {"p": 1})

    assert result == {"ok": True}
    assert fake.calls == [("enqueue_privacy_job", {"p": 1})]


def test_default_client_absent_fails_closed(monkeypatch):
    monkeypatch.setattr(supabase_service, "_client", None, raising=False)

    with pytest.raises(repository.PrivacyAcceptanceError):
        repository.call_rpc(repository._DEFAULT_CLIENT, "enqueue_privacy_job", {})
