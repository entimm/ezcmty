import json
from datetime import UTC, datetime
from hashlib import sha256

from redis.exceptions import LockError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend_app.core.errors import AppError
from backend_app.core.identifiers import new_id
from backend_app.core.resident_sessions import ResidentContext, ResidentSessionStore
from backend_app.integrations.wechat_miniapp import WechatMiniapp
from backend_app.models.admin import utc_now
from backend_app.models.miniapp import MiniappUser, PhoneBinding, PhoneVerification
from backend_app.repositories.miniapp import MiniappRepository
from backend_app.schemas import miniapp as schema


def fingerprint(data: schema.PhoneBindingCreate) -> str:
    return sha256(json.dumps(data.model_dump(), sort_keys=True).encode()).hexdigest()


def user_view(user: MiniappUser) -> schema.MiniappUser:
    return schema.MiniappUser.model_validate(user, from_attributes=True)


def phone_view(item: PhoneBinding) -> schema.PhoneBinding:
    return schema.PhoneBinding.model_validate(item, from_attributes=True)


class ResidentIdentityService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MiniappRepository(db)

    def login(
        self,
        data: schema.MiniappLogin,
        store: ResidentSessionStore,
        wechat: WechatMiniapp,
        source_ip: str,
    ) -> schema.ResidentSession:
        store.limit("login", source_ip, store.settings.resident_login_limit)
        openid = wechat.login(data.code)
        now = utc_now()
        try:
            self.db.execute(
                insert(MiniappUser)
                .values(
                    id=new_id(),
                    wechat_openid=openid,
                    enabled=True,
                    session_version=1,
                    created_at=now,
                    updated_at=now,
                    last_login_at=now,
                )
                .on_conflict_do_nothing(index_elements=[MiniappUser.wechat_openid])
            )
            user = self.db.scalar(
                select(MiniappUser)
                .where(MiniappUser.wechat_openid == openid)
                .with_for_update(of=MiniappUser)
            )
            assert user
            if not user.enabled:
                raise AppError("auth.unauthenticated")
            user.last_login_at = now
            user.updated_at = now
            self.db.commit()
            token, stored = store.create(user.id, user.session_version)
            return schema.ResidentSession(
                token=token,
                expires_at=datetime.fromtimestamp(stored.absolute_expires_at, UTC),
                user=user_view(user),
            )
        except Exception:
            self.db.rollback()
            raise

    def profile(self, ctx: ResidentContext) -> schema.MiniappUser:
        return user_view(self.repo.user(ctx))

    def list_phones(
        self, ctx: ResidentContext, page: int, page_size: int
    ) -> schema.PhoneBindingPage:
        self.repo.user(ctx)
        items, total = self.repo.bindings(ctx.user_id, page, page_size)
        return schema.PhoneBindingPage(
            items=[phone_view(i) for i in items], total=total, page=page, page_size=page_size
        )

    def bind_phone(
        self,
        ctx: ResidentContext,
        data: schema.PhoneBindingCreate,
        key: str,
        request_id: str,
        store: ResidentSessionStore,
        wechat: WechatMiniapp,
    ) -> schema.PhoneBinding:
        try:
            # Coordination only: no code, phone or exchange result is stored in Redis.
            with store.client.lock(
                f"app:resident-phone-write:{ctx.user_id}", timeout=60, blocking_timeout=1
            ):
                self.repo.user(ctx)
                previous = self.repo.verification(ctx.user_id, key)
                digest = fingerprint(data)
                if previous:
                    if previous.request_fingerprint != digest:
                        raise AppError("resident.idempotency_conflict")
                    return phone_view(self.repo.binding(ctx.user_id, previous.phone_binding_id))
                code_hash = sha256(data.code.encode()).hexdigest()
                if self.db.scalar(
                    select(PhoneVerification.id).where(
                        PhoneVerification.user_id == ctx.user_id,
                        PhoneVerification.wechat_code_hash == code_hash,
                    )
                ):
                    raise AppError("resident.idempotency_conflict")
                user = self.repo.user(ctx)
                openid = user.wechat_openid
                self.db.rollback()  # No database write transaction during the external request.
                store.limit("phone", ctx.user_id, store.settings.resident_phone_limit)
                verified = wechat.verify_phone(data.code, openid)
                if data.expected_phone is not None and data.expected_phone != verified.phone:
                    raise AppError("wechat.phone_mismatch")
                self.repo.user(ctx, lock=True, exclusive=True)
                binding = self.db.scalar(
                    select(PhoneBinding)
                    .where(
                        PhoneBinding.user_id == ctx.user_id, PhoneBinding.phone == verified.phone
                    )
                    .with_for_update(of=PhoneBinding)
                )
                now = utc_now()
                if binding is None:
                    binding = PhoneBinding(
                        id=new_id(),
                        user_id=ctx.user_id,
                        phone=verified.phone,
                        status="active",
                        first_verified_at=now,
                        last_verified_at=now,
                        row_version=1,
                    )
                    self.db.add(binding)
                else:
                    binding.status = "active"
                    binding.unbound_at = None
                    binding.last_verified_at = now
                    binding.updated_at = now
                    binding.row_version += 1
                self.db.flush()
                self.db.add(
                    PhoneVerification(
                        id=new_id(),
                        user_id=ctx.user_id,
                        phone_binding_id=binding.id,
                        method="wechat_fast",
                        wechat_code_hash=code_hash,
                        wechat_authorized_at=verified.authorized_at,
                        verified_at=now,
                        idempotency_key=key,
                        request_fingerprint=digest,
                        request_id=request_id,
                    )
                )
                self.db.commit()
                return phone_view(binding)
        except LockError:
            self.db.rollback()
            raise AppError("resident.state_changed") from None
        except Exception:
            self.db.rollback()
            raise

    def unbind_phone(self, ctx: ResidentContext, binding_id: str, version: int) -> None:
        try:
            self.repo.user(ctx, lock=True, exclusive=True)
            self.repo.binding(ctx.user_id, binding_id)
            now = utc_now()
            changed = self.db.scalar(
                update(PhoneBinding)
                .where(
                    PhoneBinding.id == binding_id,
                    PhoneBinding.user_id == ctx.user_id,
                    PhoneBinding.status == "active",
                    PhoneBinding.row_version == version,
                )
                .values(
                    status="unbound",
                    unbound_at=now,
                    updated_at=now,
                    row_version=PhoneBinding.row_version + 1,
                )
                .returning(PhoneBinding.id)
            )
            if not changed:
                raise AppError("resident.state_changed")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
