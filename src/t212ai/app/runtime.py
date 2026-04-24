from __future__ import annotations

from dataclasses import dataclass

from t212ai.guidelines.service import (
    GuidelineMemoryService,
    build_empty_guideline_document,
)
from t212ai.persistence.documents import FileBackedStructuredDocumentStore

from .config import AppSettings, get_app_settings


@dataclass(slots=True)
class AppRuntime:
    settings: AppSettings
    guideline_document_store: FileBackedStructuredDocumentStore
    guideline_memory_service: GuidelineMemoryService


def build_runtime() -> AppRuntime:
    settings = get_app_settings()
    guideline_document_store = FileBackedStructuredDocumentStore(
        settings.guideline_memory_path,
        document_factory=build_empty_guideline_document,
    )
    guideline_memory_service = GuidelineMemoryService(guideline_document_store)
    return AppRuntime(
        settings=settings,
        guideline_document_store=guideline_document_store,
        guideline_memory_service=guideline_memory_service,
    )
