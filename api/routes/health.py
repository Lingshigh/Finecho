from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health", summary="存活检查")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "service": request.app.title,
        "environment": request.app.state.settings.app_env,
    }


@router.get("/ready", summary="就绪检查")
async def ready(request: Request) -> dict:
    return {
        "status": "ready",
        "knowledge_graph_nodes": request.app.state.rag_service.graph.number_of_nodes(),
    }
