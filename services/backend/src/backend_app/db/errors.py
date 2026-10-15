from sqlalchemy.exc import IntegrityError


def is_unique_violation(exc: IntegrityError, constraint: str) -> bool:
    return (
        getattr(exc.orig, "sqlstate", None) == "23505"
        and getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == constraint
    )
