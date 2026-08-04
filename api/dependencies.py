from typing import Annotated

from fastapi import Depends, Request

from src.services.analysis_service import AnalysisService
from src.services.rag_service import GraphRAGService


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


def get_rag_service(request: Request) -> GraphRAGService:
    return request.app.state.rag_service


AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
GraphRAGServiceDep = Annotated[GraphRAGService, Depends(get_rag_service)]
