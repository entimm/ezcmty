from backend_app.core.error_catalog import ERROR_CATALOG


class AppError(Exception):
    def __init__(
        self,
        code: str,
        *,
        public_detail: str | None = None,
    ) -> None:
        if code not in ERROR_CATALOG:
            raise ValueError("Business errors must use a registered error code")
        status, title = ERROR_CATALOG[code]
        if status is None:
            raise ValueError("Business errors must have a fixed HTTP status")
        if public_detail is not None and not isinstance(public_detail, str):
            raise TypeError("Public error detail must be a string")
        super().__init__(title)
        self.code = code
        self.status_code = status
        self.public_detail = public_detail
