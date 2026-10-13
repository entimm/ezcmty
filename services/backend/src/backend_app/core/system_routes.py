from fastapi import APIRouter, Response

from backend_app.schemas.system import ErrorResponse, HealthResponse, ReadinessResponse
from backend_app.services.system import check_readiness


def create_system_router(service_name: str) -> APIRouter:
    router = APIRouter(tags=["system"], responses={500: {"model": ErrorResponse}})

    @router.get("/healthz", response_model=HealthResponse, operation_id="getHealth")
    def get_health() -> HealthResponse:
        return HealthResponse(status="ok", service=service_name)

    @router.get(
        "/readyz",
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse}},
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
