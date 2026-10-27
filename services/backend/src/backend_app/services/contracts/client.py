from dataclasses import dataclass

from pydantic import BaseModel, Field

from backend_app.domain.client.types import ClientAuthorization as ClientAuthorization


class StoredClientSession(BaseModel):
    version: int = Field(gt=0)
    absolute_expires_at: float = Field(gt=0, allow_inf_nan=False)


@dataclass(frozen=True)
class ClientContext(ClientAuthorization):
    token: str
    stored: StoredClientSession
