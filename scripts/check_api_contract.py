"""Check that every FastAPI runtime implements the shared operational contract."""

from __future__ import annotations

import json
import os
from importlib import import_module
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_CONTRACT = ROOT / "build" / "openapi" / "openapi.bundled.json"
RUNTIMES = (
    "platform_admin_api",
    "property_admin_api",
    "resident_api",
    "webhook",
)


def load_contract() -> dict[str, Any]:
    return json.loads(BUNDLED_CONTRACT.read_text(encoding="utf-8"))


def resolve_references(
    value: Any, document: dict[str, Any], seen: frozenset[str] = frozenset()
) -> Any:
    if isinstance(value, list):
        return [resolve_references(item, document, seen) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if not reference.startswith("#/"):
            raise AssertionError(f"Unbundled reference: {reference}")
        if reference in seen:
            return value
        target: Any = document
        for part in reference[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        value = {**target, **{key: item for key, item in value.items() if key != "$ref"}}
        seen = seen | {reference}
    return {key: resolve_references(item, document, seen) for key, item in value.items()}


def normalize_contract(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, list):
        result = [normalize_contract(item) for item in value]
        if parent_key in ("required", "enum", "parameters"):
            result.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return result
    if not isinstance(value, dict):
        return value
    # Names inside "properties" are data fields, even when they are named "title".
    annotations = {"title", "description", "summary", "example", "examples", "externalDocs"}
    return {
        key: normalize_contract(item, key)
        for key, item in value.items()
        if parent_key == "properties" or key not in annotations
    }


def get_operations(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    operations = {}
    for path, path_item in document.get("paths", {}).items():
        path_item = resolve_references(path_item, document)
        for method, operation in path_item.items():
            if method not in methods:
                continue
            operations[(path, method)] = normalize_contract(
                {
                    "operationId": operation.get("operationId"),
                    "tags": operation.get("tags", []),
                    "parameters": path_item.get("parameters", [])
                    + operation.get("parameters", []),
                    "requestBody": operation.get("requestBody"),
                    "responses": operation.get("responses", {}),
                    "security": operation.get("security", document.get("security", [])),
                }
            )
    return operations


def check_documents(contract: dict[str, Any], generated: dict[str, Any]) -> None:
    expected = get_operations(contract)
    actual = get_operations(generated)
    if expected.keys() != actual.keys():
        raise AssertionError(
            f"Operation mismatch: missing={sorted(expected.keys() - actual.keys())}, "
            f"unexpected={sorted(actual.keys() - expected.keys())}"
        )
    for (path, method), operation in expected.items():
        if operation != actual[(path, method)]:
            raise AssertionError(f"Contract mismatch: {method.upper()} {path}")
        for security in operation["security"]:
            for name in security:
                expected_scheme = resolve_references(
                    contract["components"]["securitySchemes"][name], contract
                )
                actual_scheme = resolve_references(
                    generated["components"]["securitySchemes"][name], generated
                )
                if normalize_contract(expected_scheme) != normalize_contract(actual_scheme):
                    raise AssertionError(f"Security scheme mismatch: {name}")


def check_runtime(contract: dict[str, Any], module_name: str) -> None:
    module = import_module(f"backend_app.runtimes.{module_name}")
    try:
        check_documents(contract, module.app.openapi())
    except AssertionError as exc:
        raise AssertionError(f"{module_name}: {exc}") from exc


def main() -> None:
    if not BUNDLED_CONTRACT.exists():
        raise SystemExit("OpenAPI bundle is missing; run `pnpm api:bundle` first")

    os.environ.setdefault(
        "APP_DATABASE_URL", "mysql+pymysql://127.0.0.1/contract"
    )
    os.environ.setdefault("APP_REDIS_URL", "redis://localhost:6379/0")
    contract = load_contract()
    for runtime in RUNTIMES:
        check_runtime(contract, runtime)
    print(f"OpenAPI contract checks passed for {len(RUNTIMES)} runtimes")


if __name__ == "__main__":
    main()
