from fastapi import APIRouter, Response

from backend_app.core.openapi import get_problem_responses, get_request_id_headers
from backend_app.core.readiness import check_readiness
from backend_app.schemas.system import HealthResponse, ReadinessResponse


def create_system_router(service_name: str) -> APIRouter:
    router = APIRouter(tags=["system"], responses=get_problem_responses(500))

    @router.get(
        "/healthz",
        response_model=HealthResponse,
        responses={200: {"headers": get_request_id_headers()}},
        operation_id="getHealth",
    )
    def get_health() -> HealthResponse:
        return HealthResponse(status="ok", service=service_name)

    @router.get(
        "/readyz",
        response_model=ReadinessResponse,
        responses={
            200: {"headers": get_request_id_headers()},
            503: {"model": ReadinessResponse, "headers": get_request_id_headers()},
        },
        operation_id="getReadiness",
    )
    def get_readiness(response: Response) -> ReadinessResponse:
        dependencies = check_readiness()
        ready = all(status == "ok" for status in dependencies.values())
        if not ready:
            response.status_code = 503
        return ReadinessResponse(
            status="ok" if ready else "not_ready",
            service=service_name,
            dependencies=dependencies,
        )

    return router
