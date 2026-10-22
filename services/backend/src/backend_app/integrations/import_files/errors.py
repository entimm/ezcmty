class ImportFileError(Exception):
    """A safe diagnostic; never include filenames, paths, or cell contents."""

    def __init__(self, code: str = "import.file_invalid") -> None:
        self.code = code
        super().__init__(code)
