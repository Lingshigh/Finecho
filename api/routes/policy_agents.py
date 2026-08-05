from fastapi import APIRouter

from api.dependencies import PolicyServiceDep
from src.models.policy_schemas import PolicyAgentStatus

router = APIRouter(prefix="/policy-agents", tags=["policy-agents"])


@router.get("/status", response_model=PolicyAgentStatus)
async def get_policy_agent_status(service: PolicyServiceDep) -> PolicyAgentStatus:
    return service.agent_status()
