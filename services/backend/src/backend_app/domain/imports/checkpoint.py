"""Strict, bounded, non-sensitive stage recovery coordinates."""

from typing import Any

from backend_app.domain.imports.fingerprints import canonical_json

MAX_CHECKPOINT_BYTES = 8192
MAX_CURSOR = 2**63 - 1


def _integer(value: Any, minimum: int = 1) -> bool:
    return type(value) is int and minimum <= value <= MAX_CURSOR


def validate_checkpoint(phase: str, value: dict[str, Any]) -> dict[str, Any]:
    """Reject unsafe/unknown coordinates instead of silently restarting work."""
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise ValueError("Invalid import checkpoint")
    if value["schema_version"] != 1:
        raise ValueError("Unsupported import checkpoint version")
    expected = {
        "precheck": {"target_preview_version", "next_row_no"},
        "apply": {"source_preview_version", "next_row_no"},
        "artifact": {
            "source_preview_version",
            "source_batch_row_version",
            "output_generation",
            "next_row_no",
            "next_part_no",
        },
    }
    if phase == "parse":
        if set(value) != {"schema_version", "source_artifact_generation", "cursor"}:
            raise ValueError("Invalid parse checkpoint fields")
        if not _integer(value["source_artifact_generation"]):
            raise ValueError("Invalid source generation")
        cursor = value["cursor"]
        if not isinstance(cursor, dict) or not _integer(cursor.get("next_row_no")):
            raise ValueError("Invalid parse cursor")
        if cursor.get("kind") == "csv_record":
            if set(cursor) != {"kind", "next_byte_offset", "next_row_no"} or not _integer(
                cursor["next_byte_offset"], 0
            ):
                raise ValueError("Invalid CSV cursor")
        elif cursor.get("kind") == "xlsx_row":
            if (
                set(cursor) != {"kind", "sheet_name", "next_row_no"}
                or not isinstance(cursor["sheet_name"], str)
                or not 1 <= len(cursor["sheet_name"]) <= 31
            ):
                raise ValueError("Invalid XLSX cursor")
        else:
            raise ValueError("Unsupported parse cursor")
    elif phase in expected:
        if set(value) != expected[phase] | {"schema_version"} or any(
            not _integer(value[key]) for key in expected[phase]
        ):
            raise ValueError("Invalid stage checkpoint fields")
    else:
        raise ValueError("Unsupported import phase")
    if len(canonical_json(value)) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Import checkpoint exceeds limit")
    # Return a fresh document so callers cannot retain mutable nested aliases.
    return {**value, **({"cursor": dict(value["cursor"])} if phase == "parse" else {})}
