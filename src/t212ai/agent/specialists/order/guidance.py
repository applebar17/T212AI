"""Reasoner and planner guidance for broker order flows."""

from __future__ import annotations


def _broker_order_reasoning_guidelines() -> list[str]:
    return [
        "Treat broker reads as the only authority for cash, positions, pending orders, and order references.",
        "Treat user-supplied public symbols, company names, and ISINs as unverified for broker execution "
        "until broker_resolve_instrument or broker portfolio context confirms the broker-native instrument.",
        "Detect broker-state dependent values such as available-cash fractions, full-position exits, and protective orders that depend on a prior fill.",
        "Treat every SELL, stop, stop-limit, trailing-stop, hedge, cover, or protective exit as holding-dependent: "
        "the broker portfolio must confirm an open position and available quantity before any sell-side order can be prepared.",
        "If the conversation includes an intended buy followed by a protective sell, reason that the protective sell "
        "depends on the buy being submitted and filled; do not prepare the sell before live broker holdings show the position.",
        "Record unresolved or ambiguous broker instruments as required evidence, not assumptions; "
        "broker-native tradable identifiers come from broker tools or broker portfolio context.",
        "Approval and rejection are Telegram callback-button events; typed chat text is ordinary conversation.",
        "Numeric broker fields must be resolved decimal values before order preparation.",
    ]


def _broker_order_planning_guidelines() -> list[str]:
    return [
        "Use broker_get_portfolio_snapshot before preparing orders that depend on cash, holdings, or available quantities.",
        "For any SELL-side order, including stop-loss, stop-limit, take-profit, close, liquidation, hedge, or protective sell, "
        "first use broker_get_portfolio_snapshot and verify the exact broker-native ticker exists in current holdings with "
        "positive quantityAvailableForTrading. If no matching holding exists, stop before broker_prepare_order_action and "
        "explain that the buy/open position must exist before placing the sell-side order.",
        "Use broker_resolve_instrument before broker_prepare_order_action when the user supplied a public ticker, "
        "company name, ISIN, or any identifier not already confirmed as broker-native by broker data.",
        "For a user-supplied ISIN, use broker_resolve_instrument before any order preparation.",
        "When the user gives only a company name or public ticker and the goal is an order, call "
        "broker_resolve_instrument first because broker candidates may include the broker-native ticker, "
        "ISIN, currency, and tradability metadata.",
        "Use broker_get_instrument_snapshot when the plan needs broker-authoritative tradability, currency, "
        "instrument type, fractional support, shortability, or provider-specific instrument metadata.",
        "Skip instrument-resolution when a prior broker tool output already provides the exact "
        "broker-native ticker; depend on that output instead.",
        "If broker_resolve_instrument returns ambiguous or not_found, stop before order preparation and ask for "
        "confirmation or a more precise ticker/exchange/currency rather than guessing.",
        "If broker_prepare_order_action returns an instrument-resolution error, use the tool output as the final "
        "failure explanation: no order was prepared, no approval was created, and the user must choose or provide "
        "a broker-native ticker.",
        "Add no-tool calculation actions for simple arithmetic from prior tool outputs, then pass the resolved decimal value into broker_prepare_order_action.",
        "Use broker_prepare_order_action or broker_prepare_cancel_action for Telegram flows; broker_place_order is outside the natural-language preparation flow.",
        "State-changing broker preparation actions must be sequential and dependent on all broker reads/calculations they require.",
        "If a protective stop or stop-limit depends on the buy fill price or executed quantity, model it as a dependent follow-up requiring that execution/fill context and a refreshed portfolio snapshot confirming the open position.",
    ]


def _broker_order_reasoning_examples() -> list[str]:
    return [
        (
            "User asks: 'Prepare a market buy for COIN using half my available cash.' "
            "Reasoning context should note that the notional amount is broker-state dependent, "
            "available cash must be read from broker_get_portfolio_snapshot, and notional_amount "
            "must remain unset until half of available_to_trade is calculated."
        ),
        (
            "User asks: 'Buy GOOGL.' Reasoning context should note that the public "
            "symbol may not be the broker-native tradable ticker, so broker instrument "
            "resolution is required before order preparation unless broker context "
            "already confirmed the ticker."
        ),
        (
            "User gives a price for a stock that was discussed as a buy candidate, then asks for a stop-limit sell. "
            "Reasoning context should note that a sell-side protective order requires an existing broker holding; "
            "if the previous buy failed, is only prepared, or has not filled, the sell cannot be prepared yet."
        )
    ]


def _broker_order_planning_examples() -> list[str]:
    return [
        (
            "Example grouped plan for cash-relative buy: "
            "group 1 sequential action broker_get_portfolio_snapshot with output_key=portfolio; "
            "group 2 sequential no-tool action calculate_notional_from_cash depending on portfolio, "
            "expected_output='resolved decimal notional amount and currency'; "
            "group 3 sequential action broker_resolve_instrument if needed; "
            "group 4 sequential action broker_prepare_order_action depending on the cash calculation "
            "and instrument resolution, passing notional_amount as a concrete decimal number."
        ),
        (
            "Example grouped plan for public-symbol buy: "
            "group 1 sequential action broker_resolve_instrument with query set to the "
            "user-provided symbol/name and output_key=instrument_resolution; "
            "group 2 sequential action broker_prepare_order_action depending on "
            "instrument_resolution, using resolvedTicker only when resolution.status is resolved. "
            "If resolution is ambiguous or not_found, stop before order preparation and ask for confirmation."
        ),
        (
            "Example grouped plan for ISIN input: "
            "group 1 sequential action broker_resolve_instrument with the user-supplied ISIN; "
            "group 2 sequential action broker_prepare_order_action only when broker resolution returns resolved."
        ),
        (
            "Example grouped plan for protective sell/stop-limit: "
            "group 1 sequential action broker_get_portfolio_snapshot with output_key=portfolio; "
            "group 2 sequential action broker_resolve_instrument only if needed to map the user symbol; "
            "group 3 sequential no-tool action verify_open_position depending on portfolio and optional resolution, "
            "expected_output='exact held broker-native ticker and available quantity, or explicit no-position blocker'; "
            "group 4 sequential action broker_prepare_order_action only if verify_open_position confirms a positive "
            "available quantity for the exact ticker. If no holding exists, stop and explain that the stock must be bought "
            "and filled before placing the protective sell."
        )
    ]
