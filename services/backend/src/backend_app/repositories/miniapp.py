from sqlalchemy import select
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.models.miniapp import MiniappUser, PhoneBinding, PhoneVerification
from backend_app.repositories.pagination import read_page


class MiniappRepository:
    def __init__(self, db: Session):
        self.db = db

    def user(
        self, user_id: str, version: int, *, lock: bool = False, exclusive: bool = False
    ) -> MiniappUser:
        query = select(MiniappUser).where(MiniappUser.id == user_id)
        if lock:
            query = query.with_for_update(read=not exclusive, of=MiniappUser)
        item = self.db.scalar(query.execution_options(populate_existing=True))
        if item is None or not item.enabled or item.session_version != version:
            raise AppError("auth.unauthenticated")
        return item

    def verification(self, user_id: str, key: str) -> PhoneVerification | None:
        return self.db.scalar(
            select(PhoneVerification).where(
                PhoneVerification.user_id == user_id, PhoneVerification.idempotency_key == key
            )
        )

    def binding(self, user_id: str, binding_id: str, *, lock: bool = False) -> PhoneBinding:
        query = select(PhoneBinding).where(
            PhoneBinding.user_id == user_id, PhoneBinding.id == binding_id
        )
        if lock:
            query = query.with_for_update(of=PhoneBinding)
        item = self.db.scalar(query.execution_options(populate_existing=True))
        if item is None:
            raise AppError("resource.not_found")
        return item

    def bindings(self, user_id: str, page: int, page_size: int) -> tuple[list[PhoneBinding], int]:
        return read_page(
            self.db,
            PhoneBinding,
            select(PhoneBinding).where(PhoneBinding.user_id == user_id),
            page=page,
            page_size=page_size,
            order=(("created_at", True), ("id", True)),
        )
