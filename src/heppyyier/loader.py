import ctypes
import os
import pathlib
import sys
import types
import warnings
from typing import List, Optional

from .builder import _resolve_lib_dir
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

        # Load dependencies first
        if deps:
            all_packages = reg.all_packages()
            order = _topo_sort(deps, all_packages)
            for dep in order:
                if dep not in self._loaded:
                    self.load(dep, verbose=verbose)

        self._setup_python_paths(record, python_paths, verbose)
        self._setup_cppyy(record, headers, libraries, verbose)
        # Don't shadow a real Python module (e.g. lhapdf SWIG bindings) with a
        # cppyy proxy. If a proper importable module exists for this name, leave
        # sys.modules alone — the C++ library has already been loaded above.
        if name not in sys.modules:
            import importlib.util
            if importlib.util.find_spec(name) is None:
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
            "lib_dir": str(_resolve_lib_dir(prefix)),
            "cppyy_namespace": name,
            "headers": [],
            "libraries": [],
            "depends_on": [],
        }

    # cling 16 (LLVM 16, shipped with cppyy ≤ 3.x) is compatible with GCC 7–13.
    # GCC 14 headers use C++23-era attributes and C library assumptions that
    # cling 16 cannot parse (fenv_t not in global namespace, _GLIBCXX_NODISCARD
    # on operator new, etc.). Injecting GCC 14 headers breaks the PCH build.
    _CLING_MAX_COMPATIBLE_GCC = 13

    def _ensure_cxx17_headers(self) -> None:
        """On Linux, ensure cppyy's PCH build uses a compatible GCC with C++17 headers.

        cppyy's rootcling inherits both CPATH and the CXX env var when building
        its PCH cache. On some HPC systems the default 'c++' is very old (e.g.
        GCC 7.5 on SUSE/NERSC) and has no <filesystem>, while 'g++' is a newer
        compatible version (GCC 13). We query g++ first, set CXX to it, and add
        its include paths to CPATH so rootcling uses the right compiler.

        Falls back to a glob scan of /usr/include/c++/ for systems where no
        compiler is in PATH (module-load required HPC nodes).
        """
        if not sys.platform.startswith("linux"):
            return
        import glob as _glob
        import shutil
        import subprocess
        import warnings

        def _has_filesystem(d: pathlib.Path) -> bool:
            return (d / "filesystem").exists()

        cpath_dirs = [pathlib.Path(p) for p in os.environ.get("CPATH", "").split(":") if p]
        if any(_has_filesystem(p) for p in cpath_dirs):
            return

        dirs_to_add: list = []

        def _add_with_arch_subdir(version_dir: pathlib.Path) -> None:
            vd = str(version_dir)
            if vd not in dirs_to_add:
                dirs_to_add.append(vd)
            for arch_config in sorted(version_dir.glob("*/bits/c++config.h")):
                arch_dir = str(arch_config.parent.parent)
                if arch_dir not in dirs_to_add:
                    dirs_to_add.append(arch_dir)

        # Strategy 1 (primary): query compilers directly.
        # Prefer g++ over c++ — on SUSE/RHEL the system 'c++' may be very old
        # (e.g. GCC 7.5 with no C++17 <filesystem>) while 'g++' is newer.
        # Set CXX so cling/rootcling uses the same compiler for its PCH build.
        for cxx_candidate in ("g++", "c++"):
            cxx = shutil.which(cxx_candidate)
            if not cxx:
                continue
            try:
                ver = subprocess.run(
                    [cxx, "-dumpversion"], capture_output=True, text=True, timeout=5,
                )
                cxx_major = int(ver.stdout.strip().split(".")[0])
            except Exception:
                continue
            if cxx_major > self._CLING_MAX_COMPATIBLE_GCC:
                continue  # too new for this cling version (GCC 14+ breaks cling 16)
            try:
                r = subprocess.run(
                    [cxx, "-v", "-x", "c++", "-E", "/dev/null"],
                    capture_output=True, text=True, timeout=10,
                )
                in_block = False
                for line in r.stderr.splitlines():
                    if "#include <...> search starts here" in line:
                        in_block = True
                        continue
                    if "End of search list" in line:
                        break
                    if in_block:
                        p = pathlib.Path(line.strip())
                        if p.is_dir() and _has_filesystem(p):
                            _add_with_arch_subdir(p)
            except Exception:
                continue
            if dirs_to_add:
                # Tell cling/rootcling to use this compiler for its PCH build
                if "CXX" not in os.environ:
                    os.environ["CXX"] = cxx
                break

        # Strategy 2 (fallback): glob well-known GCC versioned include paths.
        # Useful on nodes where no compiler is in PATH without a module load.
        if not dirs_to_add:
            for pattern in (
                "/usr/include/c++/*/filesystem",
                "/usr/local/include/c++/*/filesystem",
            ):
                for m in sorted(_glob.glob(pattern), reverse=True):
                    vdir = pathlib.Path(m).parent
                    try:
                        gcc_major = int(vdir.name.split(".")[0])
                    except (ValueError, IndexError):
                        continue
                    if gcc_major <= self._CLING_MAX_COMPATIBLE_GCC:
                        _add_with_arch_subdir(vdir)
                        break

        if not dirs_to_add:
            warnings.warn(
                "[heppyyier] No C++ headers compatible with cppyy's cling were found. "
                f"Need GCC ≤ {self._CLING_MAX_COMPATIBLE_GCC} with <filesystem>. "
                "Options: 'heyy install cppyy' (builds cling from source), "
                "'heyy install root' (uses ROOT's native cling), "
                "or load a compatible GCC module: 'module load gcc/13'.",
                UserWarning, stacklevel=4,
            )
            return

        if dirs_to_add:
            existing = os.environ.get("CPATH", "")
            os.environ["CPATH"] = ":".join(dirs_to_add) + (":" + existing if existing else "")

    def _preload_cppyy_deps(self) -> None:
        """Pre-load cppyy backend dependencies that may be missing from rpath."""
        self._ensure_cxx17_headers()
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
        if "cppyy" not in sys.modules and "ROOT" not in sys.modules:
            # Strip any DYLD/LD_LIBRARY_PATH entry that contains libcling.
            # ROOT's lib dir ends up in DYLD_LIBRARY_PATH via both `module load`
            # and the heyy Jupyter kernel spec. If pip-cppyy loads its own cling
            # while ROOT's cling is also visible, cppyy_backend crashes in
            # TThread::Init. Safe to strip here because ROOT is not yet imported.
            _cling_names = ("libcling.dylib", "libcling.so", "libCling.dylib", "libCling.so")
            for _var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
                _val = os.environ.get(_var, "")
                _parts = [p for p in _val.split(":") if p]
                _safe = [
                    p for p in _parts
                    if not any((pathlib.Path(p) / n).exists() for n in _cling_names)
                ]
                if len(_safe) != len(_parts):
                    os.environ[_var] = ":".join(_safe)
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
