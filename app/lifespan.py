from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from agent.llm import OptionalPolicyLLM
from app.config import get_settings
from src.repositories.job_repository import InMemoryJobRepository
from src.services.analysis_service import AnalysisService
from src.services.event_bus import EventBus
from src.services.rag_service import GraphRAGService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    project_root = Path(__file__).resolve().parents[1]
    rag = GraphRAGService(project_root / "data")
    repository = InMemoryJobRepository()
    event_bus = EventBus()
    llm = OptionalPolicyLLM(settings.openai_api_key, settings.openai_model)
    app.state.settings = settings
    app.state.rag_service = rag
    app.state.analysis_service = AnalysisService(repository, rag, llm, event_bus)
    yield
