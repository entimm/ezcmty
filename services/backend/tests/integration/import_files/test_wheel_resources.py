import json
import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path
from zipfile import ZipFile

from tests.support.paths import BACKEND_ROOT

from backend_app.domain.imports.registry import definition_from_mapping
from backend_app.import_definitions.catalog import get_import_registry


def _build(project: Path, output: Path) -> Path:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from setuptools.build_meta import build_wheel; build_wheel(sys.argv[1])",
            str(output),
        ],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_installed_wheels_load_current_and_retained_definitions_outside_source_tree(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    package = fixture / "src" / "imports_fixture"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (fixture / "pyproject.toml").write_text("""[build-system]
requires = ["setuptools>=75,<81"]
build-backend = "setuptools.build_meta"
[project]
name = "imports-fixture"
version = "1.0.0"
[tool.setuptools.packages.find]
where = ["src"]
[tool.setuptools.package-data]
imports_fixture = ["*.json"]
""")
    definitions = []
    for version in (1, 2):
        definition = {
            "key": "fixture",
            "name": "测试配置",
            "version_no": version,
            "adapter_key": f"fixture_v{version}",
            "fields": [{"key": "name", "label": "名称", "order": 1, "required": True}],
            "release_notes": f"v{version}",
            "released_at": "2026-10-23T00:00:00Z",
        }
        definitions.append(definition)
        (package / f"v{version}.json").write_text(json.dumps(definition), encoding="utf-8")
    expected = [definition_from_mapping(value).config_hash for value in definitions]
    production = _build(BACKEND_ROOT, tmp_path / "production-wheel")
    test_fixture = _build(fixture, tmp_path / "fixture-wheel")
    with ZipFile(production) as archive:
        assert not any(
            "imports_fixture" in name or name.startswith("tests/") for name in archive.namelist()
        )
    isolated = tmp_path / "installed"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(isolated)
    interpreter = isolated / "bin" / "python"
    uv = shutil.which("uv")
    assert uv is not None
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            str(interpreter),
            str(production),
            str(test_fixture),
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    detached = tmp_path / "detached"
    detached.mkdir()
    # Reuse installed dependency packages without executing their editable-source .pth files.
    # The application itself must still load exclusively from the newly installed wheel.
    dependency_paths = list({sysconfig.get_path("purelib"), sysconfig.get_path("platlib")})
    script = """import json
import sys
from pathlib import Path
sys.path.extend(json.loads(sys.argv[1]))
import backend_app
assert Path(backend_app.__file__).is_relative_to(Path(sys.prefix))
from importlib.resources import files
from backend_app.import_definitions.catalog import JsonImportRegistry, get_import_registry
names = ("normalize", "prepare", "required_permissions", "plan", "revalidate",
         "execute", "resolve_operation")
methods = {name: lambda *a: None for name in names}
adapter = type("Adapter", (), methods)()
registry = JsonImportRegistry.from_resources(
    "imports_fixture", ("v1.json", "v2.json"),
    adapters={"fixture_v1": adapter, "fixture_v2": adapter},
)
production = get_import_registry()
assert [item.key for item in production.list()] == ["house_owners", "houses", "property_fee_bills"]
assert {item.key: item.config_hash for item in production.list()} == json.loads(sys.argv[2])
owners = production.get("house_owners", 1)
assert owners.allowed_actor_scopes == ("property_admin",)
assert owners.allowed_scope_types == ("community",)
assert owners.required_permissions == ("property.housing.manage",)
assert owners.read_permissions == ("property.housing.read",)
assert production.get_adapter(owners.adapter_key).__class__.__name__ == "HouseOwnerImportAdapter"
assert files("backend_app.import_definitions").joinpath("house_owners/v1.json").is_file()
housing = production.get("houses", 1)
assert housing.allowed_actor_scopes == ("property_admin",)
assert housing.allowed_scope_types == ("community",)
assert production.get_adapter(housing.adapter_key).__class__.__name__ == "HouseImportAdapter"
assert files("backend_app.import_definitions").joinpath("houses/v1.json").is_file()
current = production.get("property_fee_bills", 1)
assert current.allowed_actor_scopes == ("property_admin",)
assert current.allowed_scope_types == ("community",)
assert production.get_adapter(current.adapter_key).__class__.__name__ == "BillImportAdapter"
assert files("backend_app.import_definitions").joinpath("property_fee_bills/v1.json").is_file()
assert files("backend_app.import_definitions").joinpath("catalog.py").is_file()
assert registry.get("fixture", 1).release_notes == "v1"
assert registry.get("fixture", 2).release_notes == "v2"
assert registry.get("fixture", 1, registry.get("fixture", 1).config_hash).version_no == 1
print(json.dumps([definition.config_hash for definition in registry.list()]))
"""
    completed = subprocess.run(
        [
            str(interpreter),
            "-I",
            "-c",
            script,
            json.dumps(dependency_paths),
            json.dumps({item.key: item.config_hash for item in get_import_registry().list()}),
        ],
        cwd=detached,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == expected
