from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend_app.models.imports import ImportArtifact


def source_artifact(db: Session, batch_id: str) -> ImportArtifact | None:
    return db.scalar(
        select(ImportArtifact).where(
            ImportArtifact.batch_id == batch_id, ImportArtifact.artifact_kind == "source"
        )
    )


def latest_artifact(db: Session, batch_id: str, kind: str = "error_rows") -> ImportArtifact | None:
    return db.scalar(
        select(ImportArtifact)
        .where(ImportArtifact.batch_id == batch_id, ImportArtifact.artifact_kind == kind)
        .order_by(ImportArtifact.generation.desc())
        .limit(1)
    )


def next_generation(db: Session, batch_id: str, *, checkpoint_generation: int = 0) -> int:
    """Caller holds the batch lock; unfinished output namespaces must never be reused."""
    latest = db.scalar(
        select(func.max(ImportArtifact.generation)).where(
            ImportArtifact.batch_id == batch_id, ImportArtifact.artifact_kind == "error_rows"
        )
    )
    return max(latest or 0, checkpoint_generation) + 1
