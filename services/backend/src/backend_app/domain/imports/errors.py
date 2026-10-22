"""Safe adapter execution outcomes; exception text contains only a stable code."""

import re


class ImportExecutionFailure(Exception):
    def __init__(self, code: str = "import.conflict", *, retryable: bool = False) -> None:
        if not re.fullmatch(r"import\.[a-z_]{1,96}", code):
            raise ValueError("Invalid import execution error code")
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ImportOutcomeUnknown(Exception):
    def __init__(self) -> None:
        super().__init__("import.result_uncertain")
