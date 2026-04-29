from __future__ import annotations

import logging
from pathlib import Path


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
) -> None:
    resolved_level = resolve_log_level(level)
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

    if file_path is not None and str(file_path).strip():
        target = Path(file_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(target, encoding="utf-8")
        file_handler.setLevel(resolved_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
