import copy
import subprocess
from importlib import import_module
from types import ModuleType

import pytest
from fastapi import FastAPI
from pytest import MonkeyPatch
from scripts.check_api_contract import RUNTIMES
from tests.support.paths import REPOSITORY_ROOT

from backend_app.app_factory import create_app


@pytest.fixture
def contract_tools(monkeypatch: MonkeyPatch) -> tuple[ModuleType, ModuleType]:
    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT))
    return import_module("scripts.check_api_contract"), import_module("scripts.build_error_catalog")


@pytest.fixture(scope="session")
def bundled_contract() -> None:
    # Build the authoritative files, even in a fresh checkout or after a contract edit.
    result = subprocess.run(
        ["pnpm", "api:bundle"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.fail(result.stdout + result.stderr)


def test_error_catalog_matches_authoritative_contract(
    contract_tools: tuple[ModuleType, ModuleType], bundled_contract: None
) -> None:
    checker, builder = contract_tools
    contract = checker.load_contract()
    builder.check_catalog(contract)


def test_error_catalog_rejects_duplicate_codes(
    contract_tools: tuple[ModuleType, ModuleType], bundled_contract: None
) -> None:
    checker, builder = contract_tools
    contract = checker.load_contract()
    duplicate = copy.deepcopy(contract)
    catalog = duplicate["components"]["schemas"]["ProblemDetails"]["x-error-catalog"]
    catalog["another"] = {"INTERNAL_ERROR": {"status": 500, "title": "duplicate"}}
    with pytest.raises(ValueError, match="duplicate"):
        builder.build_catalog(duplicate)


def test_error_catalog_detects_stale_generation(
    contract_tools: tuple[ModuleType, ModuleType], bundled_contract: None
) -> None:
    checker, builder = contract_tools
    contract = checker.load_contract()
    changed = copy.deepcopy(contract)
    changed["components"]["schemas"]["ProblemDetails"]["x-error-catalog"]["system"][
        "INTERNAL_ERROR"
    ]["title"] = "changed"
    with pytest.raises(AssertionError, match="stale"):
        builder.check_catalog(changed)


def test_reference_sibling_properties_preserve_envelope_and_specialize_kind(
    contract_tools: tuple[ModuleType, ModuleType],
) -> None:
    checker, _ = contract_tools
    document = {
        "components": {
            "schemas": {
                "Envelope": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": ["payment", "sharing"]},
                        "ciphertext": {"type": "string", "minLength": 1},
                    },
                    "required": ["kind", "ciphertext"],
                }
            }
        }
    }
    specialized = checker.resolve_references(
        {
            "$ref": "#/components/schemas/Envelope",
            "properties": {"kind": {"type": "string", "const": "payment"}},
        },
        document,
    )
    assert specialized["properties"] == {
        "kind": {"type": "string", "const": "payment"},
        "ciphertext": {"type": "string", "minLength": 1},
    }
    assert specialized["additionalProperties"] is False
    assert specialized["required"] == ["kind", "ciphertext"]


def test_reference_sibling_conflicting_property_constraints_are_not_discarded(
    contract_tools: tuple[ModuleType, ModuleType],
) -> None:
    checker, _ = contract_tools
    original = {"type": "string", "minLength": 10}
    document = {"components": {"schemas": {"Value": {"properties": {"value": original}}}}}
    resolved = checker.resolve_references(
        {"$ref": "#/components/schemas/Value", "properties": {"value": {"minLength": 1}}}, document
    )
    assert resolved["properties"]["value"] == {"allOf": [original, {"minLength": 1}]}


@pytest.mark.parametrize("runtime", RUNTIMES)
def test_operational_contract_matches_every_runtime(
    contract_tools: tuple[ModuleType, ModuleType], bundled_contract: None, runtime: str
) -> None:
    checker, _ = contract_tools
    contract = checker.load_contract()
    app: FastAPI = create_app(runtime)
    checker.check_documents(contract, app.openapi(), runtime=runtime)
