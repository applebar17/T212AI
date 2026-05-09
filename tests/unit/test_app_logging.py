from __future__ import annotations

import json
import logging
from logging.handlers import TimedRotatingFileHandler

from t212ai.app.logging import configure_logging, log_event


def test_configure_logging_uses_daily_json_rotation_and_noisy_logger_level(tmp_path) -> None:
    log_file = tmp_path / "app.log"

    configure_logging(
        "INFO",
        file_path=log_file,
        file_format="json",
        retention_days=3,
        third_party_level="WARNING",
    )

    file_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, TimedRotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].backupCount == 3
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_log_event_writes_json_without_none_fields_or_raw_content(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    configure_logging("INFO", file_path=log_file, file_format="json", retention_days=3)
    logger = logging.getLogger("tests.structured_logging")

    log_event(
        logger,
        "tool.call.end",
        component="tool",
        tool_name="broker_prepare_order_action",
        status="ok",
        duration_ms=12,
        error_code=None,
        message_text=None,
    )
    for handler in logging.getLogger().handlers:
        handler.flush()

    payload = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
    assert payload["event"] == "tool.call.end"
    assert payload["component"] == "tool"
    assert payload["tool_name"] == "broker_prepare_order_action"
    assert payload["status"] == "ok"
    assert payload["duration_ms"] == 12
    assert "error_code" not in payload
    assert "message_text" not in payload


def test_json_formatter_redacts_common_secret_patterns(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    configure_logging("INFO", file_path=log_file, file_format="json", retention_days=3)
    logger = logging.getLogger("tests.redaction")

    log_event(
        logger,
        "provider.error",
        component="genai",
        url=(
            "HTTP Request: POST "
            "https://api.telegram.org/bot123:secret/getUpdates?api_key=secret&ok=1"
        ),
        headers={"Authorization": "Bearer secret-token"},
    )
    for handler in logging.getLogger().handlers:
        handler.flush()

    line = log_file.read_text(encoding="utf-8").splitlines()[-1]
    assert "secret-token" not in line
    assert "bot123:secret" not in line
    assert "api_key=secret" not in line
    payload = json.loads(line)
    assert payload["headers"]["Authorization"] == "[REDACTED]"
