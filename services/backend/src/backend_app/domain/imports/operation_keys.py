"""Stable opaque logical-operation identity, reused by retries and takeovers."""

import re
from typing import Any

from backend_app.domain.imports.fingerprints import fingerprint


def validate_digest(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a lowercase SHA-256 digest")
    return value


def operation_key(
    property_company_id: str,
    template_key: str,
    operation_type: str,
    natural_key: dict[str, Any],
    input_fingerprint: str,
) -> str:
    validate_digest(input_fingerprint)
    if not property_company_id or not template_key or not operation_type or not natural_key:
        raise ValueError("Stable operation identity is required")
    return fingerprint(
        {
            "schema_version": 1,
            "property_company_id": property_company_id,
            "template_key": template_key,
            "operation_type": operation_type,
            "natural_key": natural_key,
            "input_fingerprint": input_fingerprint,
        }
    )
