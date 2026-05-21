"""Scheduler management constants."""

from __future__ import annotations


INSTRUMENT_MONITOR_TRIGGER_TYPES = frozenset(
    {
        "below_price",
        "above_price",
        "percent_change_below",
        "percent_change_above",
        "period_low_breakdown",
        "period_high_breakout",
    }
)
COMPANY_EVENT_TYPES = frozenset(
    {
        "earnings_report",
        "guidance_update",
        "filing",
        "major_news",
        "company_event",
    }
)
COMPANY_EVENT_SCHEDULE_TYPES = frozenset({"one_shot", "recurring"})
COMPANY_EVENT_FREQUENCIES = frozenset({"daily", "weekdays", "weekly"})
MARKET_REGIME_PROXY_LABELS = {
    "market": ("SPY", "market"),
    "s&p": ("SPY", "S&P 500"),
    "s&p 500": ("SPY", "S&P 500"),
    "sp500": ("SPY", "S&P 500"),
    "spy": ("SPY", "S&P 500"),
    "nasdaq": ("QQQ", "Nasdaq"),
    "nasdaq 100": ("QQQ", "Nasdaq 100"),
    "qqq": ("QQQ", "Nasdaq 100"),
    "dow": ("DIA", "Dow"),
    "dow jones": ("DIA", "Dow Jones"),
    "dia": ("DIA", "Dow Jones"),
    "russell": ("IWM", "Russell 2000"),
    "russell 2000": ("IWM", "Russell 2000"),
    "small caps": ("IWM", "small caps"),
    "small cap": ("IWM", "small caps"),
    "iwm": ("IWM", "Russell 2000"),
}
DEFAULT_MARKET_REGIME_PERCENT_CHANGE_BELOW = -3.0
DEFAULT_MARKET_REGIME_DRAWDOWN_FROM_HIGH_PCT = 5.0
MARKET_SIGNAL_CAPTURE_SCHEDULE_TYPES = frozenset({"polling", "recurring"})
MARKET_SIGNAL_CAPTURE_FREQUENCIES = frozenset({"daily", "weekdays", "weekly"})
DEFAULT_MARKET_SIGNAL_CAPTURE_POLL_SECONDS = 3600
MIN_MARKET_SIGNAL_CAPTURE_POLL_SECONDS = 900
TRADE_SETUP_ORDER_TYPES = frozenset({"MARKET", "LIMIT", "STOP", "STOP_LIMIT"})
TRADE_SETUP_SIDES = frozenset({"BUY", "SELL"})
THRESHOLD_TRIGGER_TYPES = frozenset(
    {
        "below_price",
        "above_price",
        "percent_change_below",
        "percent_change_above",
    }
)
