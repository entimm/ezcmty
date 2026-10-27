from dataclasses import dataclass


@dataclass(frozen=True)
class ClientAuthorization:
    user_id: str
    version: int


@dataclass(frozen=True)
class ClientIdentityDescriptor:
    id: str
    type: str
    display_name: str


@dataclass(frozen=True)
class IdentityLink:
    id: str
    user_id: str
    identity_type: str
    subject_id: str
    row_version: int


@dataclass(frozen=True)
class ExtraIdentityAuthorization(ClientAuthorization):
    identity_id: str
    identity_type: str
    subject_id: str
    row_version: int


@dataclass(frozen=True)
class IdentityResolution:
    display_name: str
    authorization: ExtraIdentityAuthorization
