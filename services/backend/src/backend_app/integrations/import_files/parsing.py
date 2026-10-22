from dataclasses import dataclass
from typing import Any

MAX_ROWS = 50_000
MAX_COLUMNS = 200
MAX_CELL_LENGTH = 32_767
MAX_RECORD_BYTES = MAX_COLUMNS * (MAX_CELL_LENGTH + 4)


@dataclass(frozen=True)
class ParsedRow:
    source_row_no: int
    values: tuple[Any, ...]


@dataclass(frozen=True)
class ParsedChunk:
    headers: tuple[str, ...]
    rows: tuple[ParsedRow, ...]
    next_byte_offset: int
    next_row_no: int
    sheet_name: str | None
    done: bool


def validate_headers(headers: tuple[str, ...], expected: tuple[str, ...] | None) -> None:
    from backend_app.integrations.import_files.errors import ImportFileError

    if (
        not headers
        or len(headers) > MAX_COLUMNS
        or any(not h or len(h) > MAX_CELL_LENGTH for h in headers)
        or len(set(headers)) != len(headers)
        or expected is not None
        and headers != expected
    ):
        raise ImportFileError()
