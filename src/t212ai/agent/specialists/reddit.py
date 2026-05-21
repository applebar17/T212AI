"""Reddit research specialist agent."""

from __future__ import annotations

from t212ai.data_sources.reddit import (
    REDDIT_RESEARCH_TOOLBOX,
    RedditToolRuntime,
    build_reddit_tool_mapping,
)
from t212ai.genai.tools.base import render_tool_descriptions
from t212ai.genai.tracing import set_trace_metadata, set_trace_name, traceable
from t212ai.guidelines.service import GuidelineMemoryService

from ..base import AgentProfile, BaseAgent
from ..intents import AgentIntent, IntentKind
from ..planner import TaskComplexity
from ..schemas import AgentRequest, AgentResponse


class RedditResearchAgent(BaseAgent):
    def __init__(
        self,
        reasoner,
        guideline_service: GuidelineMemoryService | None = None,
        *,
        reddit_service=None,
        max_tool_calls: int = 8,
    ) -> None:
        super().__init__(
            reasoner,
            AgentProfile(
                name="reddit_research_agent",
                purpose=(
                    "Explore whitelisted finance and business Reddit communities and "
                    "produce social-context analysis for market research."
                ),
                guidelines=(
                    "Use Reddit as community/social signal only. Look for attention, "
                    "sentiment, recurring themes, speculation, disagreement, and hype. "
                    "Do not treat Reddit claims as verified facts or broker/order inputs. "
                    "When discussion looks market-relevant, explicitly state what needs "
                    "verification through market data, news, filings, or primary sources. "
                    "Prefer concise analysis over raw post dumps, but preserve important "
                    "post_ids, subreddits, popularity proxies, and quoted themes."
                ),
                toolbox_summary=(
                    "Public Reddit JSON tools: search whitelisted finance/business "
                    "subreddits, fetch subreddit posts, and inspect a specific thread. "
                    + render_tool_descriptions(REDDIT_RESEARCH_TOOLBOX)
                ),
                task_complexity=TaskComplexity.COMPLEX,
                guideline_scopes=("global", "agent:reddit_research"),
                guideline_include_categories=("investment_preference",),
                toolbox=REDDIT_RESEARCH_TOOLBOX,
            ),
            guideline_service=guideline_service,
        )
        self.reddit_service = reddit_service
        self.max_tool_calls = max(0, int(max_tool_calls))

    @traceable(name="Reddit Research Agent Handle", run_type="chain")
    def handle(
        self,
        request: AgentRequest,
        *,
        intent: AgentIntent | None = None,
        task_complexity: TaskComplexity | None = None,
    ) -> AgentResponse:
        resolved_intent = intent or AgentIntent(kind=IntentKind.SOCIAL_RESEARCH)
        complexity = task_complexity or TaskComplexity.COMPLEX
        set_trace_name(f"{self.__class__.__name__}.handle")
        set_trace_metadata(
            agent_name=self.name,
            agent_kind="specialist",
            intent_kind=resolved_intent.kind.value,
            task_complexity=complexity.value,
            workflow="reddit_research",
        )
        if self.reddit_service is None:
            return AgentResponse(
                final_answer=(
                    "Reddit research is not configured. Set COMMUNITY_PROVIDER=reddit "
                    "and restart the runtime to enable social research."
                ),
                selected_agent=self.name,
                metadata={
                    "workflow": "reddit_research",
                    "workflow_status": "unavailable",
                },
                artifacts={"workflow": "reddit_research"},
            )

        final_answer = self.reasoner.orchestrate_with_tools(
            agent_name=self.profile.name,
            purpose=self.profile.purpose,
            guidelines=self.profile.guidelines,
            toolbox_summary=self.profile.toolbox_summary,
            user_request=request.user_message,
            toolbox=REDDIT_RESEARCH_TOOLBOX,
            tools_mapping=build_reddit_tool_mapping(
                RedditToolRuntime(service=self.reddit_service)
            ),
            chat_history=self._history_for_prompt(request.history),
            persistent_guidance=self._persistent_guidance(),
            max_tool_calls=self.max_tool_calls,
        )
        if not final_answer.strip():
            final_answer = (
                "I could not produce a useful Reddit social analysis from the available "
                "posts. Try again with a ticker, company name, theme, subreddit, or "
                "post_id."
            )
        return AgentResponse(
            final_answer=final_answer,
            selected_agent=self.name,
            metadata={
                "workflow": "reddit_research",
                "workflow_status": "ok",
                "execution_mode": "tool_orchestration",
            },
            artifacts={"workflow": "reddit_research"},
        )

