"""Bounded periodic expiry and private-object reclamation."""

from collections.abc import Generator
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from backend_app.core.config import Settings
from backend_app.integrations.import_files.errors import ImportFileError
from backend_app.integrations.import_files.storage import LocalImportStorage, StorageEntry
from backend_app.models.admin import utc_now
from backend_app.repositories.imports import control, files, queries
from backend_app.repositories.imports.batches import get_batch


class ImportRetentionService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        storage: LocalImportStorage | None = None,
    ) -> None:
        self.factory = factory
        self.settings = settings
        self._storage = storage
        self._orphan_scan: Generator[StorageEntry] | None = None

    @property
    def storage(self) -> LocalImportStorage:
        if self._storage is None:
            self._storage = LocalImportStorage(self.settings.import_storage_root)
        return self._storage

    def close(self) -> None:
        if self._orphan_scan is not None:
            self._orphan_scan.close()
            self._orphan_scan = None

    def scan(self, *, now: datetime | None = None) -> None:
        now = now or utc_now()
        deadline = monotonic() + 2
        with self.factory() as db:
            for draft in files.expired_drafts(db, now - timedelta(hours=24)):
                draft.status = "expired"
                draft.finished_at = now
                draft.updated_at = now
                draft.row_version += 1
                control.event(db, draft, "draft-expired", "expired", now)
            db.commit()
        with self.factory() as db:
            ids = [b.id for b in files.expired_batches(db, now)]
        for batch_id in ids:
            if monotonic() >= deadline:
                break
            with self.factory() as db:
                batch = get_batch(db, batch_id, lock=True)
                if batch is None or batch.retention_until > now or files.protected(db, batch):
                    continue
                objects = [(a.id, a.storage_key) for a in files.artifacts(db, batch_id)]
            removed = []
            for artifact_id, key in objects:
                try:
                    self.storage.delete(key)
                except OSError, ImportFileError:
                    continue
                removed.append(artifact_id)
            with self.factory() as db:
                batch = get_batch(db, batch_id, lock=True)
                if batch is None or batch.retention_until > now or files.protected(db, batch):
                    continue
                for artifact in files.artifacts(db, batch_id):
                    if artifact.id in removed:
                        artifact.deleted_at = now
                        artifact.original_filename = None
                        artifact.updated_at = now
                db.flush()
                # Keep values until every object's deletion has either succeeded or been retried.
                if not files.has_artifacts(db, batch_id):
                    files.clear_rows(db, batch_id, now)
                db.commit()
        with self.factory() as db:
            files.clear_operations(db, now)
            db.commit()
        if monotonic() < deadline:
            self._orphans(now, deadline)

    def _orphans(self, now: datetime, deadline: float) -> None:
        if self._orphan_scan is None:
            self._orphan_scan = self.storage.iter_objects()
        for _ in range(100):
            if monotonic() >= deadline:
                break
            try:
                entry = next(self._orphan_scan)
            except StopIteration:
                self._orphan_scan = None
                break
            if entry.modified_at >= (now - timedelta(hours=24)).timestamp():
                continue
            parts = entry.key.split("/")
            with self.factory() as db:
                if files.referenced_key(db, entry.key):
                    continue
                try:
                    batch_id = str(UUID(parts[1])) if len(parts) >= 3 else None
                except ValueError:
                    batch_id = None
                batch = get_batch(db, batch_id) if batch_id else None
                if batch:
                    tasks = queries.tasks(db, batch.id)
                    if files.protected(db, batch):
                        continue
                    if batch.status == "draft" and now < batch.created_at + timedelta(hours=24):
                        continue
                    if (
                        parts[2] == "artifact"
                        and len(parts) > 3
                        and any(
                            t.phase == "artifact"
                            and str(t.checkpoint.get("output_generation")) == parts[3]
                            and t.status in {"ready", "running", "paused"}
                            for t in tasks
                        )
                    ):
                        continue
            try:
                self.storage.delete(entry.key)
            except OSError, ImportFileError:
                continue
