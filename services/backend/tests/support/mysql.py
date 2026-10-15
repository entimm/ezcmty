from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.admin_sessions import AdminSessionStore
from backend_app.models.admin import AdminAccount
from backend_app.services.platform_admin.admin import PlatformAdminService

PASSWORD = "integration-test-password"


def platform_token(factory: sessionmaker[Session], store: AdminSessionStore) -> str:
    with factory() as db:
        PlatformAdminService(db).initialize_super_admin("root", "平台", PASSWORD)
        account = db.scalar(select(AdminAccount).where(AdminAccount.login_name == "root"))
        assert account
        account.must_change_password = False
        db.commit()
        token, _ = store.create("platform_admin", account.id, account.session_version)
        return token
