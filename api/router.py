from fastapi import APIRouter

from api.routes import analyses, artifacts, companies, policies, policy_agents, policy_imports

api_router = APIRouter()
api_router.include_router(analyses.router)
api_router.include_router(companies.router)
api_router.include_router(artifacts.router)
api_router.include_router(policies.router)
api_router.include_router(policy_imports.router)
api_router.include_router(policy_agents.router)
