import copy
from importlib import import_module
from types import ModuleType
from typing import Any

import pytest
from pytest import MonkeyPatch
from tests.support.paths import REPOSITORY_ROOT


@pytest.fixture
def contract_tools(monkeypatch: MonkeyPatch) -> tuple[ModuleType, ModuleType]:
    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT))
    return import_module("scripts.check_api_contract"), import_module("scripts.build_error_catalog")


def get_sample_contract() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"version": "test"},
        "paths": {
            "/resources": {
                "get": {
                    "operationId": "getResources",
                    "x-runtimes": ["resident_api"],
                    "parameters": [{"in": "query", "name": "page", "schema": {"type": "integer"}}],
                    "responses": {
                        "200": {
                            "headers": {"X-Request-ID": {"schema": {"type": "string"}}},
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"title": {"type": "string"}},
                                        "required": ["title"],
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


@pytest.mark.parametrize(
    "drift", ["schema", "parameter", "media", "status", "headers", "version", "revision"]
)
def test_contract_check_rejects_interface_drift(
    contract_tools: tuple[ModuleType, ModuleType], drift: str
) -> None:
    checker, _ = contract_tools
    contract = get_sample_contract()
    generated = copy.deepcopy(contract)
    operation = generated["paths"]["/resources"]["get"]
    response = operation["responses"]["200"]
    match drift:
        case "schema":
            response["content"]["application/json"]["schema"]["properties"]["title"] = {
                "type": "integer"
            }
        case "parameter":
            operation["parameters"][0]["schema"]["type"] = "string"
        case "media":
            response["content"]["text/plain"] = response["content"].pop("application/json")
        case "status":
            operation["responses"]["201"] = operation["responses"].pop("200")
        case "headers":
            response["headers"] = {}
        case "version":
            generated["openapi"] = "3.0.3"
        case "revision":
            generated["info"]["version"] = "wrong"
    with pytest.raises(AssertionError):
        checker.check_documents(contract, generated, runtime="resident_api")


def test_contract_check_enforces_runtime_ownership(
    contract_tools: tuple[ModuleType, ModuleType],
) -> None:
    checker, _ = contract_tools
    contract = get_sample_contract()
    empty_runtime = copy.deepcopy(contract)
    empty_runtime["paths"] = {}
    checker.check_documents(contract, empty_runtime, runtime="platform_admin_api")
    with pytest.raises(AssertionError, match="Operation mismatch"):
        checker.check_documents(contract, empty_runtime, runtime="resident_api")
    with pytest.raises(AssertionError, match="Operation mismatch"):
        checker.check_documents(contract, contract, runtime="property_admin_api")
    contract["paths"]["/resources"]["get"]["x-runtimes"] = ["typo"]
    with pytest.raises(AssertionError, match="Invalid runtime ownership"):
        checker.check_documents(contract, empty_runtime, runtime="resident_api")


def test_parameter_override_obeys_openapi_semantics(
    contract_tools: tuple[ModuleType, ModuleType],
) -> None:
    checker, _ = contract_tools
    contract = get_sample_contract()
    inherited = {"in": "query", "name": "page", "schema": {"type": "string"}}
    contract["paths"]["/resources"]["parameters"] = [inherited]
    generated = get_sample_contract()
    checker.check_documents(contract, generated, runtime="resident_api")


def test_bad_reference_is_rejected(contract_tools: tuple[ModuleType, ModuleType]) -> None:
    checker, _ = contract_tools
    with pytest.raises(AssertionError, match="Unbundled reference"):
        checker.resolve_references({"$ref": "missing.yaml#/Object"}, {})
