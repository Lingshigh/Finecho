from fastapi import APIRouter

from api.routes import analyses, artifacts, companies

api_router = APIRouter()
api_router.include_router(analyses.router)
api_router.include_router(companies.router)
api_router.include_router(artifacts.router)
