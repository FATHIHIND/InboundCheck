"""Failover alert data boundaries; no external Telegram or database calls."""

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.alert_dispatcher import AlertDispatcherService
from app.services.failover.omnichannel_service import telegram_alert_service
from app.services.failover.telegram_result import safe_telegram_message_id, redact_telegram_text
from app.services.supabase_client import SupabaseService
from app.workers.failover_worker import process_notification_outbox_item


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_telegram_response_cannot_reach_record_return_or_logs(success, caplog):
    service = AlertDispatcherService()
    service.set_tenant_alert_config("privacy-owner", {
        "telegram_bot_token": "synthetic-owner-token",
        "telegram_chat_id": "synthetic-owner-chat",
    })
    raw = {
        "success": success,
        "status_code": 429 if not success else 200,
        "retryable": not success,
        "retry_after": 30 if not success else 0,
        "error": "buyer.private@example.com 555-0199 synthetic-owner-token",
        "data": {"result": {"text": "buyer.private@example.com", "chat": {"id": "private-chat"}}},
    }
    caplog.set_level(logging.DEBUG)
    with patch("app.services.alert_dispatcher.telegram_alert_service.send_telegram_alert", new_callable=AsyncMock) as send, patch(
        "app.services.alert_dispatcher.supabase_service.persist_failover_log"
    ) as persist:
        send.return_value = raw
        result = await service.dispatch_failover_alert(
            user_id="privacy-owner", domain_name="owner.example", order_id="ORD-1",
            trigger_reason="bounce for buyer.private@example.com +1 (415) 555-0199",
            customer_email="buyer.private@example.com",
        )

    stored = persist.call_args.kwargs
    assert send.call_args.kwargs["bot_token"] == "synthetic-owner-token"
    assert "buyer.private@example.com" not in send.call_args.kwargs["text"]
    assert "555-0199" not in send.call_args.kwargs["text"]
    assert stored["user_id"] == "privacy-owner"
    assert stored["status"] == ("delivered" if success else "failed")
    assert stored["customer_email"] is None
    assert stored["target_chat_id"] is None
    assert stored["dispatch_payload"] == result
    assert result["success"] is success
    assert result["retryable"] is not success
    assert result["retry_after"] == (0 if success else 30)
    for forbidden in ("buyer.private@example.com", "555-0199", "private-chat", "synthetic-owner-token"):
        assert forbidden not in str(stored)
        assert forbidden not in str(result)
        assert forbidden not in caplog.text


@pytest.mark.asyncio
async def test_tenants_do_not_share_telegram_credentials_or_records():
    service = AlertDispatcherService()
    service.set_tenant_alert_config("tenant-a-privacy", {
        "telegram_bot_token": "synthetic-token-a", "telegram_chat_id": "chat-a",
    })
    service.set_tenant_alert_config("tenant-b-privacy", {
        "telegram_bot_token": "synthetic-token-b", "telegram_chat_id": "chat-b",
    })
    with patch("app.services.alert_dispatcher.telegram_alert_service.send_telegram_alert", new_callable=AsyncMock) as send, patch(
        "app.services.alert_dispatcher.supabase_service.persist_failover_log"
    ) as persist:
        send.return_value = {"success": True, "data": {"result": {"chat": {"id": "private-chat"}}}}
        for tenant in ("tenant-a-privacy", "tenant-b-privacy"):
            await service.dispatch_failover_alert(tenant, "tenant.example", "ORD-2", "bounce")

    assert [call.kwargs["bot_token"] for call in send.call_args_list] == ["synthetic-token-a", "synthetic-token-b"]
    assert [call.kwargs["chat_id"] for call in send.call_args_list] == ["chat-a", "chat-b"]
    assert [call.kwargs["user_id"] for call in persist.call_args_list] == ["tenant-a-privacy", "tenant-b-privacy"]
    assert all(call.kwargs["target_chat_id"] is None for call in persist.call_args_list)


@pytest.mark.asyncio
async def test_missing_tenant_credentials_do_not_use_platform_credentials():
    service = AlertDispatcherService()
    with patch("app.services.alert_dispatcher.settings.TELEGRAM_BOT_TOKEN", "platform-secret"), patch(
        "app.services.alert_dispatcher.settings.TELEGRAM_CHAT_ID", "platform-chat"
    ), patch("app.services.alert_dispatcher.telegram_alert_service.send_telegram_alert", new_callable=AsyncMock) as send, patch(
        "app.services.alert_dispatcher.supabase_service.persist_failover_log"
    ) as persist:
        result = await service.dispatch_failover_alert("tenant-without-credentials", "tenant.example", "ORD-3", "bounce")
    send.assert_not_called()
    assert result["success"] is False
    assert result["skipped"] is True
    assert persist.call_args.kwargs["user_id"] == "tenant-without-credentials"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 503])
async def test_provider_error_body_cannot_enter_telegram_logs_or_result(status_code, caplog):
    caplog.set_level(logging.DEBUG)
    private_body = "buyer.private@example.com private-chat synthetic-token-a"
    with patch.object(telegram_alert_service, "_mock_mode", False), patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock,
        return_value=httpx.Response(status_code, text=private_body),
    ), patch("asyncio.sleep", new_callable=AsyncMock):
        result = await telegram_alert_service.send_telegram_alert(
            bot_token="1234567890:SYNTHETIC-TOKEN", chat_id="synthetic-chat", text="test"
        )
    assert result["success"] is False
    assert result["retryable"] is (status_code == 503)
    assert private_body not in str(result)
    for forbidden in ("buyer.private@example.com", "private-chat", "synthetic-token-a"):
        assert forbidden not in caplog.text


def test_persistence_boundary_drops_raw_telegram_response_and_error():
    service = SupabaseService()
    record = service.persist_failover_log(
        user_id="privacy-tenant", channel="telegram", status="failed",
        order_id="buyer.private@example.com", store_name="buyer.private@example.com",
        domain_name="buyer.private@example.com", triggered_reason="call +1 415 555 0199",
        dispatch_payload={"success": False, "error": "buyer.private@example.com", "data": {"chat": "private-chat"}},
        error_message="buyer.private@example.com", provider_error_message="private-chat",
        customer_email="buyer.private@example.com", customer_phone="+1 415 555 0199", target_chat_id="private-chat",
    )
    assert record["user_id"] == "privacy-tenant"
    assert record["dispatch_payload"]["success"] is False
    for forbidden in ("buyer.private@example.com", "private-chat"):
        assert forbidden not in str(record)
    assert record.get("customer_phone") is None
    assert "415 555 0199" not in str(record)


def test_telegram_message_id_rejects_provider_text():
    assert safe_telegram_message_id("buyer.private@example.com") is None
    assert safe_telegram_message_id(12345) == "12345"
    assert safe_telegram_message_id("mock_tg_abcdef12", simulated=True) == "mock_tg_abcdef12"
    assert safe_telegram_message_id("mock_tg_abcdef12", simulated=False) is None
    assert redact_telegram_text("buyer.private@example.com +1 415 555 0199") == "[redacted-email] [redacted-phone]"
    assert redact_telegram_text("550 5.1.1 User unknown") == "550 5.1.1 User unknown"


@pytest.mark.asyncio
async def test_synchronous_failover_drops_raw_response_before_persistence(caplog):
    caplog.set_level(logging.DEBUG)
    with patch.object(telegram_alert_service, "get_config", return_value={"is_enabled": True, "telegram_chat_id": "private-chat"}), patch.object(
        telegram_alert_service, "get_decrypted_token", return_value="synthetic-token"
    ), patch.object(telegram_alert_service, "send_telegram_alert", new_callable=AsyncMock) as send, patch(
        "app.services.supabase_client.supabase_service.persist_failover_log", return_value={"id": "synthetic-log"}
    ) as persist:
        send.return_value = {"success": True, "data": {"text": "buyer.private@example.com", "chat": "private-chat"}}
        result = await telegram_alert_service.trigger_failover_dispatch("privacy-tenant", "ORD-4")
    assert result["dispatched"] is True
    assert persist.call_args.kwargs["target_chat_id"] is None
    assert persist.call_args.kwargs["dispatch_payload"] == result["dispatch_res"]
    for forbidden in ("buyer.private@example.com", "private-chat"):
        assert forbidden not in str(persist.call_args.kwargs)
        assert forbidden not in str(result)
        assert forbidden not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_outbox_worker_drops_raw_response_and_error(success, caplog):
    caplog.set_level(logging.DEBUG)
    item = {"id": "privacy-job", "user_id": "privacy-tenant", "payload": {"order_id": "ORD-5"},
            "attempt_count": 1, "max_attempts": 5}
    with patch("app.workers.failover_worker.omnichannel_service.get_config", return_value={
        "is_enabled": True, "telegram_chat_id": "private-chat"
    }), patch("app.workers.failover_worker.omnichannel_service.get_decrypted_token", return_value="synthetic-token"), patch(
        "app.workers.failover_worker.omnichannel_service.send_telegram_alert", new_callable=AsyncMock
    ) as send, patch("app.workers.failover_worker.repository.complete_notification_outbox") as complete, patch(
        "app.workers.failover_worker.repository.supabase.persist_failover_log"
    ) as persist, patch("app.workers.failover_worker.repository.fail_or_retry_notification_outbox") as retry:
        send.return_value = {"success": success, "retryable": not success, "retry_after": 15,
                             "error": "buyer.private@example.com", "data": {"chat": "private-chat"}}
        result = await process_notification_outbox_item(item, "privacy-worker")
    assert result is success
    if success:
        complete.assert_called_once()
        assert persist.call_args.kwargs["target_chat_id"] is None
        assert persist.call_args.kwargs["dispatch_payload"]["success"] is True
        retry.assert_not_called()
    else:
        retry.assert_called_once()
        assert retry.call_args.kwargs["error"] == "Telegram delivery failed"
        persist.assert_not_called()
    for forbidden in ("buyer.private@example.com", "private-chat"):
        assert forbidden not in caplog.text
        if success:
            assert forbidden not in str(persist.call_args.kwargs)
