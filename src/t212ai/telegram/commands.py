"""Telegram command definitions."""

HELP_COMMANDS: tuple[str, ...] = (
    "/help",
    "/summary",
    "/positions",
    "/orders",
    "/history",
    "/watchlist",
    "/analyze <ticker>",
    "/proposal <buy|sell> <ticker> ...",
    "/approve <proposal_id>",
    "/reject <proposal_id>",
    "/cancel_order <order_id>",
    "/digest now",
)


def render_help_text() -> str:
    commands = "\n".join(f"- {command}" for command in HELP_COMMANDS)
    return (
        "T212AI Telegram bridge is available.\n\n"
        "Natural-language messages will be routed to the agent once the runtime "
        "is wired. Baseline command shortcuts:\n"
        f"{commands}"
    )
