from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from backend_app.core.error_catalog import REQUEST_ID_PATTERN
from backend_app.schemas.problem import ProblemDetails


def get_request_id_headers() -> dict[str, Any]:
    return {"X-Request-ID": {"schema": {"type": "string", "pattern": REQUEST_ID_PATTERN}}}


def get_problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {
        status: {
            "description": "Problem Details",
            "headers": get_request_id_headers(),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            },
        }
        for status in statuses
    }


def configure_openapi(app: FastAPI) -> None:
    def create_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
            servers=app.servers,
        )
        problem = ProblemDetails.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        schemas.update(problem.pop("$defs", {}))
        schemas["ProblemDetails"] = problem
        for path_item in schema.get("paths", {}).values():
            for method, operation in path_item.items():
                if method not in {
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                    "options",
                    "head",
                    "trace",
                }:
                    continue
                responses = operation.get("responses", {})
                validation = responses.get("422", {}).get("content", {}).get("application/json", {})
                if validation.get("schema", {}).get("$ref") == (
                    "#/components/schemas/HTTPValidationError"
                ):
                    responses["422"] = get_problem_responses(422)[422]
        app.openapi_schema = schema
        return schema

    # FastAPI's supported customization hook is a method assignment.
    app.openapi = create_openapi  # type: ignore[method-assign]
