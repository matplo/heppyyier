import ctypes
import os
import pathlib
import sys
import types
import warnings
from typing import List, Optional

from .exceptions import PackageNotInstalledError
from .registry import get_registry


def _topo_sort(names: list, registry: dict) -> list:
    visited = set()
    order = []

    def visit(n):
        if n in visited:
            return
        visited.add(n)
        record = registry.get(n)
        if record:
            for dep in record.get("depends_on", []):
                visit(dep)
        order.append(n)

    for n in names:
        visit(n)
    return order


class Loader:
    _loaded: set = set()

    def load(
        self,
        name: str,
        version: Optional[str] = None,
        install_if_missing: bool = False,
        verbose: bool = False,
    ) -> None:
        if name in self._loaded:
            return

        reg = get_registry()

        # Check if shell-loaded version should take precedence
        shell_version = self._shell_loaded_version(name)
        record = None

        if shell_version:
            shell_prefix = os.environ.get(
                f"HEPPYYIER_LOADED_{name.upper().replace('-','_')}_PREFIX"
            )
            if shell_prefix:
                # Build a synthetic record from env vars
                prefix = pathlib.Path(shell_prefix)
                record = self._record_from_prefix(name, shell_version, prefix, reg)

        if record is None:
            record = reg.get(name)

        if record is None:
            if install_if_missing:
                from .builder import build_package
                build_package(name, version=version, verbose=verbose)
                record = get_registry().get(name)
            else:
                raise PackageNotInstalledError(
                    f"Package '{name}' is not installed. "
                    f"Run: heppyyier install {name}"
                )

        # Resolve cppyy metadata from recipe (source of truth); fall back to
        # registry fields for old entries that predate Option-B migration.
        from .recipe import find_recipe
        from .exceptions import RecipeNotFoundError
        try:
            recipe = find_recipe(
                name,
                version=record["version"],
                recipe_path=record.get("recipe_path"),
            )
            headers      = recipe.cppyy_headers
            libraries    = recipe.cppyy_libraries
            namespace    = recipe.cppyy_namespace
            deps         = recipe.depends_on
            python_paths = recipe.python_paths
        except RecipeNotFoundError:
            headers      = record.get("headers", [])
            libraries    = record.get("libraries", [])
            namespace    = record.get("cppyy_namespace") or name
            deps         = record.get("depends_on", [])
            python_paths = []

        # Warn about ROOT ↔ cppyy cling conflicts
        _CLING_PACKAGES = {"root"}
        if name in _CLING_PACKAGES and self._loaded - _CLING_PACKAGES:
            warnings.warn(
                f"Loading '{name}' after cppyy-based packages "
                f"({', '.join(sorted(self._loaded - _CLING_PACKAGES))}) "
                "is likely to conflict: ROOT bundles its own cling/cppyy. "
                "Consider importing ROOT before any heppyyier.load() calls, "
                "or use ROOT's gSystem.Load() to access other libraries.",
                stacklevel=2,
            )
        elif name not in _CLING_PACKAGES and "root" in self._loaded:
            warnings.warn(
                f"Loading '{name}' via cppyy after ROOT is already imported "
                "is likely to conflict: ROOT bundles its own cling/cppyy. "
                "Consider loading all cppyy packages before importing ROOT, "
                "or use ROOT's gSystem.Load() to access other libraries.",
                stacklevel=2,
            )

        # Load dependencies first
        if deps:
            all_packages = reg.all_packages()
            order = _topo_sort(deps, all_packages)
            for dep in order:
                if dep not in self._loaded:
                    self.load(dep, verbose=verbose)

        self._setup_python_paths(record, python_paths, verbose)
        self._setup_cppyy(record, headers, libraries, verbose)
        self._inject_proxy_module(name, namespace)
        self._loaded.add(name)

    def _shell_loaded_version(self, name: str) -> Optional[str]:
        key = f"HEPPYYIER_LOADED_{name.upper().replace('-', '_')}"
        return os.environ.get(key)

    def _record_from_prefix(
        self, name: str, version: str, prefix: pathlib.Path, reg
    ) -> Optional[dict]:
        existing = reg.get(name)
        if existing and existing.get("version") == version:
            return existing
        # Minimal record from the prefix path; cppyy details may be missing
        return {
            "version": version,
            "prefix": str(prefix),
            "include_dir": str(prefix / "include"),
            "lib_dir": str(prefix / "lib"),
            "cppyy_namespace": name,
            "headers": [],
            "libraries": [],
            "depends_on": [],
        }

    def _preload_cppyy_deps(self) -> None:
        """Pre-load cppyy backend dependencies that may be missing from rpath."""
        import sys
        _search = []
        if sys.platform == "darwin":
            _search = [
                "/opt/homebrew/lib",
                "/usr/local/lib",
                "/opt/local/lib",
            ]
        for lib_name in ("libzstd.1", "libzstd"):
            for search_dir in _search:
                candidate = pathlib.Path(search_dir) / f"{lib_name}.dylib"
                if candidate.exists():
                    try:
                        ctypes.CDLL(str(candidate), ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass
                    break

    def _setup_cppyy(
        self,
        record: dict,
        headers: List[str],
        libraries: List[str],
        verbose: bool,
    ) -> None:
        if not headers and not libraries:
            return
        self._preload_cppyy_deps()
        if "cppyy" not in sys.modules:
            _root_prefix = os.environ.get("HEPPYYIER_LOADED_ROOT_PREFIX", "")
            if _root_prefix:
                _root_lib = str(pathlib.Path(_root_prefix) / "lib")
                for _var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
                    _val = os.environ.get(_var, "")
                    _filtered = ":".join(p for p in _val.split(":") if p and p != _root_lib)
                    if _filtered != _val:
                        os.environ[_var] = _filtered
        try:
            import cppyy
        except ImportError:
            raise ImportError(
                "cppyy is not installed. Install it with: pip install cppyy"
            )

        cppyy.add_include_path(record["include_dir"])

        lib_path = pathlib.Path(record["lib_dir"])
        for lib_name in libraries:
            loaded = False
            for ext in (".dylib", ".so"):
                candidate = lib_path / f"lib{lib_name}{ext}"
                if candidate.exists():
                    if verbose:
                        print(f"Loading {candidate}")
                    try:
                        ctypes.CDLL(str(candidate), ctypes.RTLD_GLOBAL)
                        loaded = True
                        break
                    except OSError as e:
                        warnings.warn(f"ctypes.CDLL failed for {candidate}: {e}")
            if not loaded:
                try:
                    cppyy.load_library(lib_name)
                except Exception as e:
                    warnings.warn(f"Could not load library '{lib_name}': {e}")

        for header in headers:
            try:
                cppyy.include(header)
            except Exception as e:
                warnings.warn(f"Could not include '{header}': {e}")

    def _setup_python_paths(
        self,
        record: dict,
        python_paths: List[str],
        verbose: bool,
    ) -> None:
        if not python_paths:
            return
        prefix = pathlib.Path(record["prefix"])
        for rel in python_paths:
            full = str(prefix / rel)
            if full not in sys.path:
                sys.path.insert(0, full)
                if verbose:
                    print(f"[heppyyier] Added to sys.path: {full}")

    def _inject_proxy_module(self, name: str, ns_name: str) -> None:
        ns_name = ns_name or name

        proxy = types.ModuleType(name)
        proxy.__doc__ = f"heppyyier cppyy proxy for {name} (namespace: {ns_name})"
        proxy.__path__ = []  # type: ignore[assignment]
        proxy.__package__ = name

        def __getattr__(attr: str):
            import cppyy
            # Support nested namespaces like "fastjet::contrib"
            ns = cppyy.gbl
            for part in ns_name.split("::"):
                ns = getattr(ns, part, None)
                if ns is None:
                    raise AttributeError(
                        f"cppyy namespace '{ns_name}' not found. "
                        f"Ensure '{name}' loaded correctly."
                    )
            return getattr(ns, attr)

        proxy.__getattr__ = __getattr__  # type: ignore[attr-defined]

        # Convenience: expose gbl directly on the proxy
        import cppyy
        proxy.gbl = cppyy.gbl  # type: ignore[attr-defined]
        proxy.cppyy = cppyy  # type: ignore[attr-defined]

        sys.modules[name] = proxy

    def loaded_names(self) -> List[str]:
        return list(self._loaded)

    def unload(self, name: str) -> None:
        warnings.warn(
            f"cppyy cannot unload shared libraries at runtime. "
            f"'{name}' will remain active for this Python session. "
            "Use shell-level 'module unload' before starting a new Python session.",
            stacklevel=2,
        )


_loader = Loader()


def get_loader() -> Loader:
    return _loader
