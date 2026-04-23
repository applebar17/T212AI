"""Rolling chat history management for agent context."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, Field


ChatRole = Literal["user", "assistant"]


class ChatHistoryMessage(BaseModel):
    chat_id: str
    role: ChatRole
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = Field(default_factory=dict)

    def to_llm_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class ChatHistoryWindow(BaseModel):
    chat_id: str
    messages: list[ChatHistoryMessage] = Field(default_factory=list)
    retained_count: int = 0
    selected_count: int = 0

    def to_llm_messages(self) -> list[dict[str, str]]:
        return [message.to_llm_message() for message in self.messages]


class ChatHistoryPolicy(BaseModel):
    max_messages_per_chat: int = 30
    context_messages: int = 16
    include_history: bool = True


class ChatHistoryStore(Protocol):
    def append(self, message: ChatHistoryMessage) -> None: ...

    def get_recent(self, chat_id: str, limit: int) -> list[ChatHistoryMessage]: ...

    def count(self, chat_id: str) -> int: ...

    def clear(self, chat_id: str) -> None: ...


class InMemoryChatHistoryStore:
    def __init__(self, *, max_messages_per_chat: int = 30) -> None:
        self.max_messages_per_chat = max(1, int(max_messages_per_chat))
        self._messages: dict[str, deque[ChatHistoryMessage]] = defaultdict(
            lambda: deque(maxlen=self.max_messages_per_chat)
        )

    def append(self, message: ChatHistoryMessage) -> None:
        self._messages[message.chat_id].append(message)

    def extend(self, messages: Iterable[ChatHistoryMessage]) -> None:
        for message in messages:
            self.append(message)

    def get_recent(self, chat_id: str, limit: int) -> list[ChatHistoryMessage]:
        resolved_limit = max(0, int(limit))
        if resolved_limit == 0:
            return []
        return list(self._messages[str(chat_id)])[-resolved_limit:]

    def count(self, chat_id: str) -> int:
        return len(self._messages[str(chat_id)])

    def clear(self, chat_id: str) -> None:
        self._messages.pop(str(chat_id), None)


class ChatHistoryManager:
    def __init__(
        self,
        store: ChatHistoryStore | None = None,
        policy: ChatHistoryPolicy | None = None,
    ) -> None:
        self.policy = policy or ChatHistoryPolicy()
        self.store = store or InMemoryChatHistoryStore(
            max_messages_per_chat=self.policy.max_messages_per_chat
        )

    def get_context_window(
        self,
        chat_id: str | int,
        *,
        include_history: bool | None = None,
        limit: int | None = None,
    ) -> ChatHistoryWindow:
        resolved_chat_id = str(chat_id)
        should_include = (
            self.policy.include_history if include_history is None else include_history
        )
        retained_count = self.store.count(resolved_chat_id)
        if not should_include:
            return ChatHistoryWindow(
                chat_id=resolved_chat_id,
                retained_count=retained_count,
                selected_count=0,
            )
        resolved_limit = limit if limit is not None else self.policy.context_messages
        messages = self.store.get_recent(resolved_chat_id, resolved_limit)
        return ChatHistoryWindow(
            chat_id=resolved_chat_id,
            messages=messages,
            retained_count=retained_count,
            selected_count=len(messages),
        )

    def record_user_message(
        self,
        chat_id: str | int,
        content: str,
        *,
        metadata: dict[str, str] | None = None,
    ) -> ChatHistoryMessage:
        return self._record(chat_id, "user", content, metadata=metadata)

    def record_assistant_message(
        self,
        chat_id: str | int,
        content: str,
        *,
        metadata: dict[str, str] | None = None,
    ) -> ChatHistoryMessage:
        return self._record(chat_id, "assistant", content, metadata=metadata)

    def _record(
        self,
        chat_id: str | int,
        role: ChatRole,
        content: str,
        *,
        metadata: dict[str, str] | None,
    ) -> ChatHistoryMessage:
        message = ChatHistoryMessage(
            chat_id=str(chat_id),
            role=role,
            content=str(content),
            metadata=metadata or {},
        )
        self.store.append(message)
        return message
