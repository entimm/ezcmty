import csv
from pathlib import Path
from typing import BinaryIO

from backend_app.integrations.import_files.errors import ImportFileError
from backend_app.integrations.import_files.parsing import (
    MAX_CELL_LENGTH,
    MAX_COLUMNS,
    MAX_RECORD_BYTES,
    MAX_ROWS,
    ParsedChunk,
    ParsedRow,
    validate_headers,
)
from backend_app.integrations.import_files.storage import MAX_SOURCE_BYTES


class _PhysicalLines:
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.row_no = 1
        self.record_bytes = 0

    def __iter__(self) -> _PhysicalLines:
        return self

    def __next__(self) -> str:
        line = self.source.readline(MAX_RECORD_BYTES + 1)
        if not line:
            raise StopIteration
        self.record_bytes += len(line)
        if self.record_bytes > MAX_RECORD_BYTES or b"\x00" in line:
            raise ImportFileError()
        self.row_no += line.count(b"\n")
        if not line.endswith(b"\n"):
            self.row_no += 1
        try:
            return line.decode("utf-8")
        except UnicodeError as error:
            raise ImportFileError() from error


def parse_csv_chunk(
    path: str | Path,
    *,
    next_byte_offset: int = 0,
    next_row_no: int = 1,
    limit: int = 500,
    expected_headers: tuple[str, ...] | None = None,
) -> ParsedChunk:
    """Replay bounded input to authenticate a complete UTF-8 record cursor before seeking work."""
    if not 1 <= limit <= 1000 or next_byte_offset < 0 or next_row_no < 1:
        raise ImportFileError()
    if Path(path).stat().st_size > MAX_SOURCE_BYTES:
        raise ImportFileError("import.file_too_large")
    try:
        with Path(path).open("rb") as source:
            if source.read(3) != b"\xef\xbb\xbf":
                source.seek(0)
            lines = _PhysicalLines(source)
            reader = csv.reader(lines, strict=True)
            headers = tuple(next(reader, ()))
            validate_headers(headers, expected_headers)
            rows: list[ParsedRow] = []
            total_rows = 0
            matched = next_byte_offset == 0
            if matched and next_row_no not in {1, lines.row_no}:
                raise ImportFileError()
            while True:
                offset, row_no = source.tell(), lines.row_no
                if not matched and offset == next_byte_offset:
                    if row_no != next_row_no:
                        raise ImportFileError()
                    matched = True
                if not matched and offset > next_byte_offset:
                    raise ImportFileError()
                if matched and len(rows) >= limit:
                    done = not source.read(1)
                    source.seek(offset)
                    return ParsedChunk(headers, tuple(rows), offset, row_no, None, done)
                lines.record_bytes = 0
                values = next(reader, None)
                if values is None:
                    if not matched:
                        raise ImportFileError()
                    return ParsedChunk(headers, tuple(rows), offset, row_no, None, True)
                if not values or not any(value.strip() for value in values):
                    continue
                total_rows += 1
                if (
                    total_rows > MAX_ROWS
                    or len(values) > MAX_COLUMNS
                    or len(values) != len(headers)
                    or any(len(value) > MAX_CELL_LENGTH for value in values)
                ):
                    raise ImportFileError()
                if matched:
                    rows.append(ParsedRow(row_no, tuple(values)))
    except (csv.Error, UnicodeError, OSError) as error:
        raise ImportFileError() from error
