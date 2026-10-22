"""Ordinary file result passed from application services to HTTP assembly."""

from dataclasses import dataclass
from typing import BinaryIO


@dataclass(frozen=True)
class FileDownload:
    source: BinaryIO
    filename: str
    media_type: str
    size_bytes: int
