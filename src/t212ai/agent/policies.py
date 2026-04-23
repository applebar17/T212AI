"""Policy and guardrail primitives."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserPolicy(BaseModel):
    environment: str = "demo"
    base_currency: str = "EUR"
    allowed_tickers: list[str] = Field(default_factory=list)
    blocked_tickers: list[str] = Field(default_factory=list)
    max_order_value: float | None = None
    max_position_value: float | None = None
    max_single_name_weight_pct: float | None = None
    max_daily_turnover: float | None = None
    allow_extended_hours: bool = False
    require_confirmation_for_live: bool = True

