from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from t212ai.agent import (
    AgentReasoner,
    AgentRequest,
    LogDiagnosticAgent,
    MainOrchestratorAgent,
    build_specialist_agents,
)
from t212ai.agent.intents import AgentIntent, IntentKind
from t212ai.app.config import get_app_settings
from t212ai.app.runtime import build_runtime
from t212ai.diagnostics import (
    DIAGNOSTIC_LOGS_TOOLBOX,
    LogFileNavigator,
    diagnostic_logs_tail,
)


class DiagnosticFakeGenAIClient:
    def __init__(self) -> None:
        self.max_tool_calls: list[int | None] = []
        self.called_tools: list[str] = []

    def chat_model_for(self, purpose: str | None = None) -> str:
        return f"{purpose or 'default'}-model"

    def handle_params(
        self,
        system_prompt: str,
        chat_messages: object,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        toolbox=None,
        **kwargs: object,
    ) -> dict[str, object]:
        del system_prompt, model, temperature, toolbox, kwargs
        return {"messages": chat_messages}

    def call_openai(
        self,
        params: dict[str, object],
        tools_mapping: dict[str, object] | None = None,
        toolbox=None,
        include_tool_meta: bool = False,
        max_tool_calls: int | None = None,
    ):
        del params, include_tool_meta
        self.max_tool_calls.append(max_tool_calls)
        if tools_mapping is not None and getattr(toolbox, "name", None) == "diagnostic_logs":
            self.called_tools.append("diagnostic_logs_tail")
            tail_result = tools_mapping["diagnostic_logs_tail"](
                limit=5,
                level="ERROR",
                logger=None,
                event=None,
                component=None,
                agent_name=None,
                selected_agent=None,
                step=None,
                tool_name=None,
                status=None,
                error_type=None,
                error_code=None,
                chat_id=None,
                message_id=None,
                request_id=None,
                contains=None,
            )
            record = (tail_result.data or {}).get("records", [])[0]
            self.called_tools.append("diagnostic_logs_context")
            tools_mapping["diagnostic_logs_context"](
                line_number=record["line_number"],
                before=1,
                after=1,
            )
            content = (
                "Finding: the request hit a provider error. "
                f"Evidence: {record['timestamp']} {record['event']} "
                f"{record['error_code']}."
            )
        else:
            content = "No diagnostic tools were used."
        return _fake_chat_response(content)


class RoutingFakeGenAIClient(DiagnosticFakeGenAIClient):
    def call_openai(
        self,
        params: dict[str, object],
        tools_mapping: dict[str, object] | None = None,
        toolbox=None,
        include_tool_meta: bool = False,
        max_tool_calls: int | None = None,
    ):
        del include_tool_meta, max_tool_calls
        messages = params.get("messages") or []
        text = str(messages[-1]["content"]).lower() if messages else ""
        if (
            tools_mapping is not None
            and getattr(toolbox, "name", None) == "orchestrator_routing"
            and "logs" in text
        ):
            tools_mapping["delegate_to_log_diagnostic_agent"](
                task_brief="Investigate the recent log error.",
                expected_output="Return a concise diagnostic explanation.",
                intent_kind=IntentKind.DEBUG_LOGS.value,
                entities=[],
            )
            return _fake_chat_response("Diagnostic route complete.")
        return super().call_openai(
            params,
            tools_mapping=tools_mapping,
            toolbox=toolbox,
            include_tool_meta=False,
        )


class RuntimeFakeGenAIClient(DiagnosticFakeGenAIClient):
    def __init__(self, settings) -> None:
        del settings
        super().__init__()


def test_log_file_navigator_tail_query_context_counts_and_malformed_lines(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "app.log"
    _write_log(
        log_path,
        [
            {
                "timestamp": "2026-05-10T10:00:00Z",
                "level": "INFO",
                "logger": "t212ai.telegram.bridge",
                "event": "telegram.request.received",
                "component": "telegram",
                "chat_id": "123",
                "message_id": "9",
                "message": "received summary",
            },
            "not-json but token=secret should be safe",
            {
                "timestamp": "2026-05-10T10:01:00Z",
                "level": "ERROR",
                "logger": "t212ai.genai.client",
                "event": "llm.call.error",
                "component": "genai",
                "agent_name": "market_analyst",
                "step": "call_openai",
                "status": "error",
                "error_type": "BadRequestError",
                "error_code": "contentfilter",
                "chat_id": "123",
                "message": "provider failed https://example.test?a=1&api_key=super-secret",
            },
            {
                "timestamp": "2026-05-10 10:02:00,123",
                "level": "INFO",
                "logger": "t212ai.agent.reasoning",
                "event": "agent.tool_orchestration.end",
                "component": "agent",
                "agent_name": "market_analyst",
                "status": "ok",
                "chat_id": "123",
            },
        ],
    )
    navigator = LogFileNavigator(log_path, max_records=10)

    tail = navigator.tail(limit=2)
    assert [record.line_number for record in tail.records] == [3, 4]
    assert tail.matched_count == 4

    query = navigator.query(
        since="2026-05-10T10:00:30Z",
        until="2026-05-10T10:01:30Z",
        level="ERROR",
        contains="contentfilter",
    )
    assert len(query.records) == 1
    assert query.records[0].error_code == "contentfilter"
    assert "super-secret" not in (query.records[0].message or "")

    context = navigator.context(line_number=query.records[0].line_number, before=1, after=1)
    assert [record.line_number for record in context.records] == [2, 3, 4]
    assert "token=secret" not in (context.records[0].message or "")

    counts = navigator.counts(group_by="error_code", chat_id="123")
    assert {"value": "contentfilter", "count": 1} in counts["counts"]


def test_diagnostic_tool_reports_missing_log_file(tmp_path: Path) -> None:
    result = diagnostic_logs_tail(
        navigator=LogFileNavigator(tmp_path / "missing.log"),
        limit=5,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "log_file_unavailable"


def test_diagnostic_toolbox_is_read_only_log_tools_only() -> None:
    assert set(DIAGNOSTIC_LOGS_TOOLBOX.tools_by_name) == {
        "diagnostic_logs_tail",
        "diagnostic_logs_query",
        "diagnostic_logs_context",
        "diagnostic_logs_counts",
    }


def test_log_diagnostic_agent_uses_bounded_tool_orchestration(tmp_path: Path) -> None:
    log_path = tmp_path / "app.log"
    _write_log(
        log_path,
        [
            {
                "timestamp": "2026-05-10T10:01:00Z",
                "level": "ERROR",
                "logger": "t212ai.genai.client",
                "event": "llm.call.error",
                "component": "genai",
                "status": "error",
                "error_code": "contentfilter",
            }
        ],
    )
    fake_client = DiagnosticFakeGenAIClient()
    agent = LogDiagnosticAgent(
        AgentReasoner(fake_client),  # type: ignore[arg-type]
        navigator=LogFileNavigator(log_path),
        max_tool_calls=10,
    )

    response = agent.handle(
        AgentRequest(user_message="debug the recent logs", chat_id="chat"),
        intent=AgentIntent(kind=IntentKind.DEBUG_LOGS),
    )

    assert fake_client.max_tool_calls == [10]
    assert fake_client.called_tools == [
        "diagnostic_logs_tail",
        "diagnostic_logs_context",
    ]
    assert "contentfilter" in response.final_answer
    assert "2026-05-10T10:01:00Z" in response.final_answer
    assert response.metadata["workflow"] == "log_diagnostics"


def test_orchestrator_exposes_log_diagnostic_tool_only_when_agent_exists(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "app.log"
    _write_log(
        log_path,
        [
            {
                "timestamp": "2026-05-10T10:01:00Z",
                "level": "ERROR",
                "event": "llm.call.error",
                "error_code": "contentfilter",
            }
        ],
    )
    reasoner = AgentReasoner(RoutingFakeGenAIClient())  # type: ignore[arg-type]
    without_agent = MainOrchestratorAgent(reasoner)
    assert (
        "delegate_to_log_diagnostic_agent"
        not in without_agent.orchestrator_toolbox.tools_by_name
    )

    diagnostic_agent = LogDiagnosticAgent(
        reasoner,
        navigator=LogFileNavigator(log_path),
    )
    specialists = build_specialist_agents(
        reasoner,
        log_diagnostic_agent=diagnostic_agent,
    )
    with_agent = MainOrchestratorAgent(reasoner, specialists=specialists)

    response = with_agent.handle(
        AgentRequest(user_message="please debug the logs", chat_id="chat")
    )

    assert "delegate_to_log_diagnostic_agent" in with_agent.orchestrator_toolbox.tools_by_name
    assert response.metadata["route"] == "log_diagnostic_agent"


def test_runtime_gates_log_diagnostic_agent_by_env(monkeypatch, tmp_path: Path) -> None:
    import t212ai.app.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "GenAIClient", RuntimeFakeGenAIClient)
    base_env = {
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "openai-key",
        "GUIDELINE_MEMORY_PATH": str(tmp_path / "guidelines.json"),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "APP_LOG_FILE_PATH": str(tmp_path / "app.log"),
    }

    disabled_runtime = build_runtime(get_app_settings(env=base_env))
    assert disabled_runtime.log_diagnostic_agent is None
    assert disabled_runtime.main_orchestrator is not None
    assert (
        "delegate_to_log_diagnostic_agent"
        not in disabled_runtime.main_orchestrator.orchestrator_toolbox.tools_by_name
    )

    enabled_env = {
        **base_env,
        "LOG_DIAGNOSTIC_AGENT_ENABLED": "true",
        "LOG_DIAGNOSTIC_MAX_TOOL_CALLS": "6",
        "LOG_DIAGNOSTIC_MAX_RECORDS": "42",
        "LOG_DIAGNOSTIC_MAX_BYTES": "4096",
    }
    enabled_runtime = build_runtime(get_app_settings(env=enabled_env))

    assert enabled_runtime.log_diagnostic_agent is not None
    assert enabled_runtime.log_diagnostic_agent.max_tool_calls == 6
    assert enabled_runtime.log_diagnostic_agent.navigator is not None
    assert enabled_runtime.log_diagnostic_agent.navigator.max_records == 42
    assert enabled_runtime.log_diagnostic_agent.navigator.max_bytes == 4096
    assert enabled_runtime.main_orchestrator is not None
    assert (
        "delegate_to_log_diagnostic_agent"
        in enabled_runtime.main_orchestrator.orchestrator_toolbox.tools_by_name
    )


def _write_log(path: Path, records: list[dict[str, object] | str]) -> None:
    lines = []
    for record in records:
        if isinstance(record, str):
            lines.append(record)
        else:
            lines.append(json.dumps(record, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fake_chat_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=None,
                )
            )
        ]
    )
