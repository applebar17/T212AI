from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from typing import Any

import pytest

from t212ai.app.bootstrap import ProviderAssessment, assess_settings
from t212ai.app.config import AppSettings, get_app_settings
from t212ai.app.runtime import AppRuntime, build_runtime
from t212ai.brokers.tools import (
    BrokerToolRuntime,
    broker_get_portfolio_snapshot,
    broker_list_historical_orders,
    broker_list_pending_orders,
    broker_prepare_order,
)
from t212ai.genai.models import ToolResult


pytestmark = pytest.mark.integration

RUN_ENV_VAR = "T212AI_RUN_BROKER_INTEGRATION"
TEST_SYMBOL_ENV_VAR = "T212AI_BROKER_TEST_SYMBOL"
TRUTHY = {"1", "true", "yes", "y", "on"}


@pytest.fixture()
def live_broker_runtime(tmp_path: Path) -> AppRuntime:
    if str(os.getenv(RUN_ENV_VAR, "")).strip().lower() not in TRUTHY:
        pytest.skip(
            f"Set {RUN_ENV_VAR}=1 to run live broker integration checks against "
            "the configured BROKER_PROVIDER."
        )

    settings = _broker_only_settings(get_app_settings(), tmp_path=tmp_path)
    assessment = assess_settings(settings)
    _assert_broker_structurally_ready(assessment.providers["broker"])

    runtime = build_runtime(settings)
    broker_component_errors = {
        key: value
        for key, value in runtime.component_errors.items()
        if key in {"trading212", "alpaca_broker"}
    }
    if broker_component_errors:
        pytest.fail(
            "Broker runtime construction failed: "
            + json.dumps(broker_component_errors, sort_keys=True)
        )
    if runtime.broker_read_service is None:
        pytest.fail("Broker read service was not wired by build_runtime().")
    return runtime


@pytest.fixture()
def broker_tool_runtime(live_broker_runtime: AppRuntime) -> BrokerToolRuntime:
    return BrokerToolRuntime(
        broker_read_service=live_broker_runtime.broker_read_service,
        broker_execution_service=live_broker_runtime.broker_execution_service,
        broker_provider=live_broker_runtime.settings.broker_provider,
        allow_state_changes=False,
    )


def test_configured_broker_can_read_portfolio_snapshot(
    live_broker_runtime: AppRuntime,
    broker_tool_runtime: BrokerToolRuntime,
) -> None:
    result = broker_get_portfolio_snapshot(runtime=broker_tool_runtime)

    _assert_tool_ok(result, tool_name="broker_get_portfolio_snapshot")
    assert result.data["provider"] == live_broker_runtime.settings.broker_provider
    snapshot = result.data["snapshot"]
    assert isinstance(snapshot, dict)
    assert isinstance(snapshot.get("account"), dict)
    assert isinstance(snapshot.get("positions"), list)
    assert isinstance(snapshot.get("pendingOrders"), list)
    assert result.output is not None
    assert "broker-authoritative" in result.output


def test_configured_broker_can_read_orders_for_reconciliation(
    broker_tool_runtime: BrokerToolRuntime,
) -> None:
    pending = broker_list_pending_orders(runtime=broker_tool_runtime)
    history = broker_list_historical_orders(
        cursor=None,
        ticker=None,
        limit=1,
        runtime=broker_tool_runtime,
    )

    _assert_tool_ok(pending, tool_name="broker_list_pending_orders")
    _assert_tool_ok(history, tool_name="broker_list_historical_orders")
    assert isinstance(pending.data["orders"], list)
    assert isinstance(history.data["page"]["items"], list)


def test_configured_broker_can_prepare_order_without_submitting(
    live_broker_runtime: AppRuntime,
    broker_tool_runtime: BrokerToolRuntime,
) -> None:
    symbol = os.getenv(TEST_SYMBOL_ENV_VAR) or _default_test_symbol(
        live_broker_runtime.settings.broker_provider
    )

    result = broker_prepare_order(
        order_type="MARKET",
        side="BUY",
        ticker=symbol,
        quantity="1",
        limit_price=None,
        stop_price=None,
        time_in_force="DAY",
        extended_hours=False,
        runtime=broker_tool_runtime,
    )

    _assert_tool_ok(result, tool_name="broker_prepare_order")
    prepared = result.data["preparedOrder"]
    assert prepared["brokerProvider"] == live_broker_runtime.settings.broker_provider
    assert prepared["ticker"]
    if (
        live_broker_runtime.settings.broker_provider.strip().lower() != "trading212"
        or "_" in symbol
    ):
        assert prepared["ticker"] == symbol.upper()
    assert prepared["orderFingerprint"]


def _broker_only_settings(settings: AppSettings, *, tmp_path: Path) -> AppSettings:
    return replace(
        settings,
        llm_provider="none",
        openai_api_key=None,
        azure_openai_enabled=False,
        azure_openai_endpoint=None,
        azure_openai_api_key=None,
        telegram_bot_token=None,
        telegram_allowed_chat_id=None,
        telegram_allowed_user_id=None,
        market_data_provider="none",
        market_intelligence_provider="none",
        disclosure_provider="none",
        community_provider="none",
        search_provider="none",
        yahoo_enabled=False,
        alpha_vantage_enabled=False,
        reddit_enabled=False,
        searxng_enabled=False,
        guideline_memory_path=str(tmp_path / "guidelines.json"),
        database_url=f"sqlite:///{tmp_path / 'broker-integration.db'}",
    )


def _assert_broker_structurally_ready(provider: ProviderAssessment) -> None:
    if not provider.enabled:
        pytest.fail("BROKER_PROVIDER is disabled. Set BROKER_PROVIDER=trading212 or alpaca.")
    if provider.ready:
        return
    missing = ", ".join(provider.missing_keys) or "none"
    errors = "; ".join(provider.errors) or "none"
    pytest.fail(
        f"Broker provider '{provider.label}' is not structurally ready. "
        f"Missing: {missing}. Errors: {errors}."
    )


def _assert_tool_ok(result: ToolResult, *, tool_name: str) -> None:
    if result.status == "ok":
        return
    if result.error is None:
        pytest.fail(f"{tool_name} returned status={result.status!r} without error details.")
    pytest.fail(
        f"{tool_name} failed. "
        f"code={result.error.code!r}; "
        f"type={result.error.type!r}; "
        f"message={result.error.message!r}; "
        f"hint={result.error.hint!r}; "
        f"details={_safe_json(result.error.details)}"
    )


def _safe_json(value: Any) -> str:
    try:
        rendered = json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        rendered = str(value)
    if len(rendered) <= 1000:
        return rendered
    return rendered[:997] + "..."


def _default_test_symbol(provider: str) -> str:
    if str(provider).strip().lower() == "trading212":
        return "AAPL_US_EQ"
    return "AAPL"
