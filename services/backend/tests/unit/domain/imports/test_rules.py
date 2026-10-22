from typing import Any

import pytest

from backend_app.domain.imports.checkpoint import validate_checkpoint
from backend_app.domain.imports.fingerprints import fingerprint
from backend_app.domain.imports.lifecycle import validate_transition
from backend_app.domain.imports.operation_keys import operation_key


@pytest.mark.parametrize(
    "phase,value",
    [
        (
            "parse",
            {
                "schema_version": 1,
                "source_artifact_generation": 1,
                "cursor": {"kind": "csv_record", "next_byte_offset": 31, "next_row_no": 2},
            },
        ),
        (
            "parse",
            {
                "schema_version": 1,
                "source_artifact_generation": 1,
                "cursor": {"kind": "xlsx_row", "sheet_name": "数据", "next_row_no": 2},
            },
        ),
        ("precheck", {"schema_version": 1, "target_preview_version": 1, "next_row_no": 2}),
        ("apply", {"schema_version": 1, "source_preview_version": 1, "next_row_no": 2}),
        (
            "artifact",
            {
                "schema_version": 1,
                "source_preview_version": 1,
                "source_batch_row_version": 3,
                "output_generation": 1,
                "next_row_no": 2,
                "next_part_no": 1,
            },
        ),
    ],
)
def test_stage_checkpoint_accepts_bounded_v1_coordinates(phase: str, value: dict[str, Any]) -> None:
    assert validate_checkpoint(phase, value) == value


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"schema_version": 2, "next_row_no": 2, "target_preview_version": 1},
        {"schema_version": True, "next_row_no": 2, "target_preview_version": 1},
        {"schema_version": 1, "next_row_no": False, "target_preview_version": 1},
        {"schema_version": 1, "next_row_no": 0, "target_preview_version": 1},
        {"schema_version": 1, "next_row_no": 2, "target_preview_version": 1, "row": "private"},
    ],
)
def test_checkpoint_rejects_unknown_sensitive_and_non_integer_fields(value: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        validate_checkpoint("precheck", value)


def test_canonical_fingerprint_and_operation_identity_are_stable() -> None:
    digest = fingerprint({"name": "中文", "id": 1})
    assert digest == fingerprint({"id": 1, "name": "中文"})
    key = operation_key("company", "records", "record.create", {"code": "a"}, digest)
    assert key == operation_key("company", "records", "record.create", {"code": "a"}, digest)
    assert key != operation_key("another", "records", "record.create", {"code": "a"}, digest)


def test_unknown_results_prevent_terminal_transition() -> None:
    with pytest.raises(ValueError):
        validate_transition("executing", "completed", uncertain_rows=1)
    with pytest.raises(ValueError):
        validate_transition("completed", "executing")
