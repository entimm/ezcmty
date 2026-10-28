import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from importlib.resources import files
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

from backend_app.domain.imports.registry import ImportDefinition, definition_from_mapping


class JsonImportRegistry:
    def __init__(
        self,
        definitions: Iterable[ImportDefinition] = (),
        adapters: Mapping[str, Any] | None = None,
    ) -> None:
        bindings = dict(adapters or {})
        catalog: dict[tuple[str, int], ImportDefinition] = {}
        for definition in definitions:
            try:
                released = datetime.fromisoformat(definition.released_at)
            except ValueError:
                raise ValueError("Import definition requires a release timestamp") from None
            if released.utcoffset() is None:
                raise ValueError("Import release timestamp must include a timezone")
            identity = definition.key, definition.version_no
            if identity in catalog:
                raise ValueError("Duplicate import definition version")
            if definition.adapter_key not in bindings:
                raise ValueError("Missing import adapter binding")
            adapter = bindings[definition.adapter_key]
            if any(
                not callable(getattr(adapter, method, None))
                for method in (
                    "normalize",
                    "prepare",
                    "required_permissions",
                    "plan",
                    "revalidate",
                    "execute",
                    "resolve_operation",
                )
            ):
                raise ValueError("Invalid import adapter binding")
            presentation = ("presentation_fields", "presentation", "summary_fields")
            if any(hasattr(adapter, method) for method in presentation) and not all(
                callable(getattr(adapter, method, None)) for method in presentation
            ):
                raise ValueError("Incomplete import presentation binding")
            catalog[identity] = definition
        self._definitions = MappingProxyType(catalog)
        self._adapters = MappingProxyType(bindings)

    @classmethod
    def from_resources(
        cls,
        package: str,
        resource_names: Iterable[str],
        *,
        adapters: Mapping[str, Any],
    ) -> JsonImportRegistry:
        definitions: list[ImportDefinition] = []
        resources = files(package)
        for name in resource_names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or path.suffix != ".json":
                raise ValueError("Invalid import definition resource")
            value = json.loads(resources.joinpath(*path.parts).read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Invalid import definition")
            definitions.append(definition_from_mapping(value))
        return cls(definitions, adapters)

    def get(self, key: str, version_no: int, config_hash: str | None = None) -> ImportDefinition:
        definition = self._definitions.get((key, version_no))
        if definition is None:
            raise ValueError("import.template_unavailable")
        if config_hash is not None and definition.config_hash != config_hash:
            raise ValueError("import.template_drift")
        return definition

    def list(self) -> tuple[ImportDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def get_adapter(self, adapter_key: str) -> Any:
        try:
            return self._adapters[adapter_key]
        except KeyError as error:
            raise ValueError("import.template_unavailable") from error


def get_import_registry() -> JsonImportRegistry:
    from backend_app.services.worker.imports.adapters.bills import BillImportAdapter
    from backend_app.services.worker.imports.adapters.fee_bases import FeeBasisImportAdapter
    from backend_app.services.worker.imports.adapters.house_owners import HouseOwnerImportAdapter
    from backend_app.services.worker.imports.adapters.houses import HouseImportAdapter

    return JsonImportRegistry.from_resources(
        "backend_app.import_definitions",
        (
            "property_fee_bills/v1.json",
            "houses/v1.json",
            "house_owners/v1.json",
            "property_fee_basis_versions/v1.json",
        ),
        adapters={
            "property_fee_bills_v1": BillImportAdapter(),
            "property_fee_basis_versions_v1": FeeBasisImportAdapter(),
            "houses_v1": HouseImportAdapter(),
            "house_owners_v1": HouseOwnerImportAdapter(),
        },
    )
