from sqlalchemy import text

from backend_app.db.session import get_engine


def check_database_connection() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
