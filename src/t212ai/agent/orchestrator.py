"""Top-level agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from .base import AgentProfile, BaseAgent
from .intents import AgentIntent, IntentKind
from .planner import TaskComplexity
from .reasoning import AgentReasoner
from .schemas import AgentRequest, AgentResponse
from .specialists import (
    CompanyAnalystAgent,
    MarketAnalystAgent,
    OrderAgent,
    PortfolioAnalystAgent,
)


@dataclass(slots=True)
class SpecialistAgents:
    portfolio: PortfolioAnalystAgent
    order: OrderAgent
    market: MarketAnalystAgent
    company: CompanyAnalystAgent

    def by_key(self) -> dict[str, BaseAgent]:
        return {
            "portfolio": self.portfolio,
            "order": self.order,
            "market": self.market,
            "company": self.company,
        }


class MainOrchestratorAgent(BaseAgent):
    def __init__(
        self,
        reasoner: AgentReasoner,
        specialists: SpecialistAgents | None = None,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="main_orchestrator",
                purpose="Route Telegram requests to the right specialist agent.",
                guidelines=(
                    "Prefer deterministic routing when the user's requested task is clear. "
                    "Ask for clarification when the target task or ticker/order is ambiguous."
                ),
                toolbox_summary=(
                    "Delegation tools: portfolio_analyst, order_agent, market_analyst, "
                    "company_analyst. The orchestrator delegates; specialists plan actions."
                ),
                task_complexity=TaskComplexity.EASY,
            ),
        )
        self.specialists = specialists or build_specialist_agents(reasoner)

    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or classify_message(request.user_message)
        if resolved_intent.kind == IntentKind.HELP:
            return AgentResponse(
                final_answer=(
                    "I can route requests to portfolio, order, market, and company "
                    "analysis agents. Ask a natural-language question or use /help."
                ),
                selected_agent=self.name,
                metadata={"intent": resolved_intent.kind.value},
            )

        selected = self._select_specialist(resolved_intent, request.user_message)
        if selected is None:
            plan = self.plan(
                request,
                intent=resolved_intent,
                task_complexity=task_complexity or TaskComplexity.EASY,
            )
            return AgentResponse(
                final_answer=(
                    "I could not confidently route this request yet. "
                    "Please specify whether it is about portfolio, orders, market, "
                    "or a company/ticker."
                ),
                selected_agent=self.name,
                plan=plan,
                metadata={"intent": resolved_intent.kind.value, "route": "unknown"},
            )

        response = selected.handle(request, intent=resolved_intent)
        response.metadata.update(
            {
                "orchestrator": self.name,
                "intent": resolved_intent.kind.value,
                "route": selected.name,
            }
        )
        return response

    def _select_specialist(
        self,
        intent: AgentIntent,
        message: str,
    ) -> BaseAgent | None:
        del message
        if intent.kind in {
            IntentKind.PLACE_ORDER,
            IntentKind.CANCEL_ORDER,
            IntentKind.REVIEW_PENDING_ORDERS,
            IntentKind.PROPOSE_TRADE,
        }:
            return self.specialists.order
        if intent.kind in {
            IntentKind.PORTFOLIO_SUMMARY,
            IntentKind.PORTFOLIO_ATTENTION_SCAN,
            IntentKind.REBALANCE,
        }:
            return self.specialists.portfolio
        if intent.kind == IntentKind.ANALYZE_INSTRUMENT:
            return self.specialists.company
        if intent.kind == IntentKind.UNKNOWN and intent.entities.get("domain") == "market":
            return self.specialists.market
        if intent.kind == IntentKind.UNKNOWN:
            return None
        return self.specialists.market


class AgentOrchestrator:
    """Compatibility fallback classifier used before the full agent runtime is wired."""

    def classify_fallback(self, message: str) -> AgentIntent:
        return classify_message(message)


def build_specialist_agents(reasoner: AgentReasoner) -> SpecialistAgents:
    return SpecialistAgents(
        portfolio=PortfolioAnalystAgent(reasoner),
        order=OrderAgent(reasoner),
        market=MarketAnalystAgent(reasoner),
        company=CompanyAnalystAgent(reasoner),
    )


def classify_message(message: str) -> AgentIntent:
    text = message.strip().lower()
    if text in {"/help", "help"}:
        return AgentIntent(kind=IntentKind.HELP, confidence=1.0)
    if any(word in text for word in ("cancel", "order status")):
        return AgentIntent(kind=IntentKind.CANCEL_ORDER, confidence=0.85)
    if any(word in text for word in ("pending order", "orders", "open order")):
        return AgentIntent(kind=IntentKind.REVIEW_PENDING_ORDERS, confidence=0.8)
    if any(word in text for word in ("buy", "sell", "place order", "trade")):
        return AgentIntent(kind=IntentKind.PROPOSE_TRADE, confidence=0.8)
    if any(word in text for word in ("portfolio", "position", "holding", "allocation")):
        return AgentIntent(kind=IntentKind.PORTFOLIO_SUMMARY, confidence=0.8)
    if any(word in text for word in ("attention", "risk", "exposure", "rebalance")):
        return AgentIntent(kind=IntentKind.PORTFOLIO_ATTENTION_SCAN, confidence=0.82)
    if any(word in text for word in ("market", "macro", "commodity", "gainers", "losers")):
        return AgentIntent(kind=IntentKind.UNKNOWN, entities={"domain": "market"}, confidence=0.55)
    if any(word in text for word in ("analyze", "company", "ticker", "earnings", "analyst")):
        return AgentIntent(kind=IntentKind.ANALYZE_INSTRUMENT, confidence=0.75)
    return AgentIntent(kind=IntentKind.UNKNOWN, entities={"message": message}, confidence=0.0)
