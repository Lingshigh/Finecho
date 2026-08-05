from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from agent.llm import OptionalPolicyLLM
from app.config import get_settings
from src.repositories.job_repository import InMemoryJobRepository
from src.repositories.policy_repository import InMemoryPolicyRepository
from src.services.analysis_service import AnalysisService
from src.services.event_bus import EventBus
from src.services.policy_agents import OptionalPolicyAgentLLM, PolicyAgentOrchestrator
from src.services.policy_service import PolicyService
from src.services.rag_service import GraphRAGService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    project_root = Path(__file__).resolve().parents[1]
    rag = GraphRAGService(project_root / "data")
    repository = InMemoryJobRepository()
    policy_repository = InMemoryPolicyRepository()
    event_bus = EventBus()
    llm = OptionalPolicyLLM(settings.openai_api_key, settings.openai_model)
    policy_agent_llm = OptionalPolicyAgentLLM(
        settings.openai_api_key,
        settings.openai_model,
        settings.policy_agent_timeout_seconds,
    )
    policy_agents = PolicyAgentOrchestrator(
        policy_agent_llm,
        enabled=settings.policy_agents_enabled,
    )
    policy_service = PolicyService(policy_repository, policy_agents)
    await policy_service.bootstrap()
    app.state.settings = settings
    app.state.rag_service = rag
    app.state.analysis_service = AnalysisService(repository, rag, llm, event_bus)
    app.state.policy_service = policy_service
    yield
