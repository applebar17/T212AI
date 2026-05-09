from __future__ import annotations

import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "openai._base_client",
    "telegram",
    "telegram.ext",
    "telegram.request",
)

STANDARD_EVENT_FIELDS = (
    "component",
    "request_id",
    "chat_id",
    "user_id",
    "message_id",
    "agent_name",
    "selected_agent",
    "step",
    "tool_name",
    "status",
    "duration_ms",
    "error_type",
    "error_code",
)

_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|authorization|password|credential|refresh[_-]?token)",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_BOT_TOKEN_PATTERN = re.compile(r"/bot[^/\s]+")
_URL_PATTERN = re.compile(r"https?://[^\s\"']+")
_URL_SECRET_PARAMS = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "password",
}


def resolve_log_level(level: int | str | None) -> int:
    if isinstance(level, int):
        return level
    raw = str(level or "").strip().upper()
    if not raw:
        return logging.INFO
    return int(getattr(logging, raw, logging.INFO))


def configure_logging(
    level: int | str = logging.INFO,
    *,
    file_path: str | Path | None = None,
    file_format: str = "json",
    retention_days: int = 3,
    third_party_level: int | str = logging.WARNING,
) -> None:
    resolved_level = resolve_log_level(level)
    resolved_third_party_level = resolve_log_level(third_party_level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(resolved_level)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(resolved_level)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    _configure_noisy_loggers(resolved_third_party_level)

    if file_path is not None and str(file_path).strip():
        target = Path(file_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            file_handler = TimedRotatingFileHandler(
                target,
                when="midnight",
                backupCount=max(0, int(retention_days)),
                encoding="utf-8",
            )
        except OSError as exc:
            root.warning("File logging disabled for %s: %s", target, exc)
            return
        file_handler.setLevel(resolved_level)
        if str(file_format or "json").strip().lower() == "json":
            file_handler.setFormatter(JsonLogFormatter())
        else:
            file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def log_event(
    logger: logging.Logger,
    event: str,
    level: int | str = logging.INFO,
    **fields: Any,
) -> None:
    resolved_level = resolve_log_level(level)
    if not logger.isEnabledFor(resolved_level):
        return
    event_fields = {
        key: _redact(value)
        for key, value in fields.items()
        if value is not None
    }
    logger.log(
        resolved_level,
        event,
        extra={
            "event": event,
            "event_fields": event_fields,
        },
    )


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = str(event)
        event_fields = getattr(record, "event_fields", None)
        if isinstance(event_fields, dict):
            payload.update(
                {
                    str(key): _redact(value)
                    for key, value in event_fields.items()
                    if value is not None
                }
            )
        if record.exc_info:
            payload["exception"] = _redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)


def _configure_noisy_loggers(level: int) -> None:
    for name in NOISY_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(level)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _SECRET_KEY_PATTERN.search(str(key))
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    text = _BOT_TOKEN_PATTERN.sub("/bot[REDACTED]", text)
    text = _URL_PATTERN.sub(lambda match: _redact_url_query(match.group(0)), text)
    return text


def _redact_url_query(text: str) -> str:
    try:
        split = urlsplit(text)
    except ValueError:
        return text
    if not split.scheme or not split.netloc or not split.query:
        return text
    query = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        query.append((key, "[REDACTED]" if key.lower() in _URL_SECRET_PARAMS else value))
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(query),
            split.fragment,
        )
    )
