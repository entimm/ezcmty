"""Trusted property targets and a narrow, current-authorization boundary."""

from dataclasses import dataclass
from typing import Any, Protocol

from backend_app.core.errors import AppError


@dataclass(frozen=True)
class BusinessActor:
    id: str
    display_name: str
    permissions: frozenset[str]


class BusinessAuthority(Protocol):
    def authorize(
        self,
        context: PropertyBusinessContext,
        actions: frozenset[str],
        *,
        lock: bool,
        shared: bool,
    ) -> BusinessActor: ...

    def record(
        self,
        context: PropertyBusinessContext,
        actor: BusinessActor,
        *,
        action: str,
        target_type: str,
        target_id: str,
        request_id: str,
        metadata: dict[str, Any],
    ) -> None: ...


@dataclass(frozen=True)
class PropertyBusinessContext:
    company_id: str
    actor_id: str
    source: str
    authority: BusinessAuthority

    def __post_init__(self) -> None:
        if not self.company_id or not self.actor_id or not self.source:
            raise AppError("auth.forbidden")

    def require(
        self,
        *actions: str,
        lock: bool = False,
        shared: bool = False,
    ) -> BusinessActor:
        # Authority re-reads current facts; no durable permission snapshot grants access.
        required = frozenset(actions)
        actor = self.authority.authorize(self, required, lock=lock, shared=shared)
        if actor.id != self.actor_id or not required <= actor.permissions:
            raise AppError("auth.forbidden")
        return actor

    def record(
        self,
        *,
        actor: BusinessActor,
        action: str,
        target_type: str,
        target_id: str,
        request_id: str,
        metadata: dict[str, Any],
    ) -> None:
        self.authority.record(
            self,
            actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id,
            metadata=metadata,
        )
