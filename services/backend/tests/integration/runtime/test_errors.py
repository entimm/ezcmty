import json
import logging
from collections.abc import Iterator
from typing import Annotated

import httpx
import pytest
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from pytest import LogCaptureFixture, MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError

from backend_app.app_factory import create_app
from backend_app.core.error_catalog import ERROR_CATALOG, ERROR_TYPE_PREFIX
from backend_app.core.errors import AppError
from backend_app.core.logging import JsonFormatter, request_id_context
from backend_app.core.openapi import get_problem_responses

SECRET = "diagnostic-secret-marker"


class InputData(BaseModel):
    amount: int = Field(gt=0)
    password: str


@pytest.fixture
def app(monkeypatch: MonkeyPatch) -> FastAPI:
    # Preserve capture handlers while exercising the real third-party log suppression.
    monkeypatch.setattr("logging.basicConfig", lambda **kwargs: None)
    application = create_app("test-errors")

    @application.post("/test/validation")
    def create_input(data: Annotated[InputData, Body()]) -> InputData:
        return data

    @application.get("/test/conflict", responses=get_problem_responses(409))
    def get_conflict() -> None:
        raise AppError("resource.conflict")

    @application.get("/test/http/{status}")
    def get_http_error(status: int) -> None:
        raise HTTPException(
            status_code=status,
            detail=SECRET,
            headers={"WWW-Authenticate": "Bearer", "X-Request-ID": "wrong-id"},
        )

    @application.get("/test/system/{kind}")
    def get_system_error(kind: str) -> None:
        match kind:
            case "connection":
                raise RedisConnectionError(SECRET)
            case "mysql":
                raise OperationalError(SECRET, {}, RuntimeError(2003, SECRET))
            case "pool":
                raise DatabaseTimeoutError(SECRET)
            case "redis":
                raise RedisResponseError(SECRET)
            case "integrity":
                raise IntegrityError(SECRET, {"password": SECRET}, RuntimeError(SECRET))
            case "sql":
                raise ProgrammingError(SECRET, {"password": SECRET}, RuntimeError(SECRET))
            case "unknown-driver":
                raise OperationalError(SECRET, {}, RuntimeError({"password": SECRET}))
            case _:
                raise RuntimeError(SECRET) from ValueError(SECRET)

    @application.get("/test/stream")
    def get_stream() -> StreamingResponse:
        def stream_chunks() -> Iterator[bytes]:
            yield b"started"
            raise RuntimeError(SECRET)

        return StreamingResponse(stream_chunks(), media_type="text/plain")

    @application.post("/test/webhook")
    def receive_webhook() -> Response:
        # A provider protocol explicitly returns text, including failure acknowledgments.
        return Response("FAIL", status_code=503, media_type="text/plain")

    return application


def assert_problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    data = response.json()
    assert data["status"] == status
    assert data["code"] == code
    assert data["type"] == ERROR_TYPE_PREFIX + code
    assert data["instance"] == "urn:request:" + data["request_id"]
    assert data["request_id"] == response.headers["x-request-id"]
    assert "message" not in data and "details" not in data and "data" not in data
    assert SECRET not in response.text


def test_normal_response_is_direct_data(app: FastAPI) -> None:
    response = TestClient(app).get("/healthz")
    assert response.json() == {"status": "ok", "service": "test-errors"}
    assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize("body", [{"amount": SECRET, "password": SECRET}, {"amount": -1}])
def test_validation_error_is_safe_and_matches_schema(app: FastAPI, body: dict[str, object]) -> None:
    response = TestClient(app).post("/test/validation", json=body)
    assert_problem(response, 422, "VALIDATION_ERROR")
    assert response.json()["errors"]
    assert all(set(issue) == {"location", "type"} for issue in response.json()["errors"])
    declaration = app.openapi()["paths"]["/test/validation"]["post"]["responses"]["422"]
    assert set(declaration["content"]) == {"application/problem+json"}
    assert declaration["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetails"
    }


def test_business_conflict_uses_registered_status(app: FastAPI) -> None:
    assert_problem(TestClient(app).get("/test/conflict"), 409, "resource.conflict")


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "auth.unauthenticated"), (403, "auth.forbidden"), (499, "HTTP_ERROR")],
)
def test_http_errors_preserve_status_and_headers(app: FastAPI, status: int, code: str) -> None:
    response = TestClient(app).get(f"/test/http/{status}", headers={"X-Request-ID": "trace-1"})
    assert_problem(response, status, code)
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers.get_list("x-request-id") == ["trace-1"]


def test_route_and_method_errors(app: FastAPI) -> None:
    client = TestClient(app)
    assert_problem(client.get("/unknown"), 404, "resource.not_found")
    response = client.post("/healthz")
    assert_problem(response, 405, "request.method_not_allowed")
    assert response.headers["allow"] == "GET"


def test_http_error_type_is_stable_when_business_codes_share_status(
    app: FastAPI, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend_app.core.exception_handlers.ERROR_CATALOG",
        {"account.locked": (403, "Account locked"), **ERROR_CATALOG},
    )
    assert_problem(TestClient(app).get("/test/http/403"), 403, "auth.forbidden")


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("connection", 503, "system.dependency_unavailable"),
        ("mysql", 503, "system.dependency_unavailable"),
        ("pool", 503, "system.dependency_unavailable"),
        ("redis", 500, "INTERNAL_ERROR"),
        ("integrity", 500, "INTERNAL_ERROR"),
        ("sql", 500, "INTERNAL_ERROR"),
        ("unknown-driver", 500, "INTERNAL_ERROR"),
        ("unknown", 500, "INTERNAL_ERROR"),
    ],
)
def test_system_error_classification_and_safe_diagnostics(
    app: FastAPI, caplog: LogCaptureFixture, kind: str, status: int, code: str
) -> None:
    caplog.set_level(logging.INFO)
    response = TestClient(app).get(
        f"/test/system/{kind}?token={SECRET}",
        headers={"Authorization": f"Bearer {SECRET}", "X-Request-ID": "system-trace"},
    )
    assert_problem(response, status, code)
    assert SECRET not in caplog.text
    diagnostics = next(record for record in caplog.records if "diagnostics=" in record.message)
    assert diagnostics.getMessage().find('"function": "get_system_error"') >= 0
    assert '"line":' in diagnostics.getMessage()
    assert '"error_type":' in diagnostics.getMessage()
    assert "status=" in caplog.text
    assert request_id_context.get() == "-"


def test_error_response_and_json_logs_use_same_request_id(
    app: FastAPI, caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(caplog.handler, "formatter", JsonFormatter("test-errors"))
    caplog.set_level(logging.INFO)
    response = TestClient(app).get(
        "/test/system/unknown", headers={"X-Request-ID": "json-log-trace"}
    )
    assert_problem(response, 500, "INTERNAL_ERROR")
    logs = [json.loads(line) for line in caplog.text.splitlines()]
    request_logs = [
        entry for entry in logs if entry["message"].startswith(("request_failed ", "http_request "))
    ]
    assert len(request_logs) == 2
    assert {entry["request_id"] for entry in request_logs} == {response.json()["request_id"]}
    assert SECRET not in caplog.text
    assert request_id_context.get() == "-"


def test_readiness_keeps_state_response_and_safe_diagnostics(
    app: FastAPI, caplog: LogCaptureFixture, monkeypatch: MonkeyPatch
) -> None:
    def fail_dependency() -> None:
        raise RedisConnectionError(SECRET)

    monkeypatch.setattr("backend_app.core.readiness.check_database_connection", fail_dependency)
    monkeypatch.setattr("backend_app.core.readiness.get_redis", fail_dependency)
    response = TestClient(app).get("/readyz")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "not_ready",
        "service": "test-errors",
        "dependencies": {"mysql": "unavailable", "redis": "unavailable"},
    }
    diagnostics = [record for record in caplog.records if "diagnostics=" in record.getMessage()]
    assert len(diagnostics) == 2
    assert all(
        "code=system.dependency_unavailable" in record.getMessage() for record in diagnostics
    )
    assert SECRET not in caplog.text and SECRET not in response.text


@pytest.mark.parametrize("supplied", ["invalid id", "a" * 65, "injected\tvalue"])
def test_invalid_request_id_is_regenerated(app: FastAPI, supplied: str) -> None:
    response = TestClient(app).get("/unknown", headers={"X-Request-ID": supplied})
    assert_problem(response, 404, "resource.not_found")
    assert response.headers["x-request-id"] != supplied


def test_started_response_is_not_replaced(app: FastAPI, caplog: LogCaptureFixture) -> None:
    with pytest.raises(RuntimeError, match="Response aborted") as caught:
        TestClient(app).get("/test/stream")
    assert SECRET not in str(caught.value)
    assert caught.value.__suppress_context__
    assert SECRET not in caplog.text
    assert request_id_context.get() == "-"


def test_external_protocol_response_is_preserved(app: FastAPI) -> None:
    response = TestClient(app).post("/test/webhook")
    assert response.status_code == 503
    assert response.text == "FAIL"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["x-request-id"]
