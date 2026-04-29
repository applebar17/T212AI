"""Telegram-friendly plain-text formatting helpers."""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[*+•]\s+")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?=\S)(.+?)(?<=\S)\*(?!\*)")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!_)_(?=\S)(.+?)(?<=\S)_(?!_)")
_DOUBLE_UNDERSCORE_RE = re.compile(r"__(?=\S)(.+?)(?<=\S)__")
_CODE_RE = re.compile(r"`([^`]+)`")
_RULE_RE = re.compile(r"^\s*---+\s*$")
_EXCESS_BLANKS_RE = re.compile(r"\n{3,}")


def normalize_telegram_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        if _RULE_RE.match(line):
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            line = heading.group(1).strip()
        line = _BULLET_RE.sub("- ", line)
        line = _BOLD_RE.sub(r"\1", line)
        line = _DOUBLE_UNDERSCORE_RE.sub(r"\1", line)
        line = _ITALIC_STAR_RE.sub(r"\1", line)
        line = _ITALIC_UNDERSCORE_RE.sub(r"\1", line)
        line = _CODE_RE.sub(r"\1", line)
        lines.append(line)
    normalized = "\n".join(lines)
    normalized = _EXCESS_BLANKS_RE.sub("\n\n", normalized)
    return normalized.strip()
