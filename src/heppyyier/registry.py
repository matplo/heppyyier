import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

from .config import get_registry_path


class Registry:
    def __init__(self, path: Optional[pathlib.Path] = None):
        self._path = path or get_registry_path()
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            return json.loads(self._path.read_text())
        return {"schema_version": 1, "packages": {}}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def register(self, name: str, record: dict) -> None:
        record["installed_at"] = datetime.now(timezone.utc).isoformat()
        self._data["packages"][name] = record
        self.save()

    def get(self, name: str) -> Optional[dict]:
        return self._data["packages"].get(name)

    def is_installed(self, name: str) -> bool:
        return name in self._data["packages"]

    def all_packages(self) -> dict:
        return dict(self._data["packages"])

    def remove(self, name: str) -> None:
        self._data["packages"].pop(name, None)
        self.save()


_registry: Optional[Registry] = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
