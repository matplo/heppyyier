import os
import pathlib
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]


def _load_project_config() -> dict:
    candidate = pathlib.Path.cwd() / ".heppyyier.toml"
    if candidate.exists():
        with open(candidate, "rb") as f:
            return tomllib.load(f)
    return {}


def _default_packages_dir() -> pathlib.Path:
    # Inside a virtual environment → keep packages alongside the venv itself
    if sys.prefix != sys.base_prefix:
        return pathlib.Path(sys.prefix) / "heppyyier_packages"
    return pathlib.Path.cwd() / "packages"


def get_packages_dir() -> pathlib.Path:
    """Root of the permanent package store: <packages_dir>/<name>/<version>/.

    Resolution order:
      1. HEPPYYIER_PACKAGES_DIR env var  (preferred)
      2. HEPPYYIER_BUILD_DIR env var      (legacy alias)
      3. .heppyyier.toml  packages_dir key
      4. .heppyyier.toml  build_dir key   (legacy alias)
      5. <venv>/heppyyier_packages/  when running inside a venv
      6. ./packages/  otherwise
    """
    for key in ("HEPPYYIER_PACKAGES_DIR", "HEPPYYIER_BUILD_DIR"):
        if key in os.environ:
            return pathlib.Path(os.environ[key]).resolve()
    cfg = _load_project_config()
    for key in ("packages_dir", "build_dir"):
        if key in cfg:
            return pathlib.Path(cfg[key]).resolve()
    return _default_packages_dir().resolve()


def get_build_dir() -> pathlib.Path:
    """Alias for get_packages_dir() — kept for call-site compatibility."""
    return get_packages_dir()


def get_registry_path() -> pathlib.Path:
    return get_packages_dir() / "registry.json"


def get_log_dir() -> pathlib.Path:
    return get_packages_dir() / "logs"


def get_recipe_cache_dir() -> pathlib.Path:
    if "HEPPYYIER_RECIPE_CACHE_DIR" in os.environ:
        return pathlib.Path(os.environ["HEPPYYIER_RECIPE_CACHE_DIR"]).resolve()
    return get_packages_dir() / "recipe-cache"


def get_recipe_sources_path() -> pathlib.Path:
    return get_packages_dir() / "recipe-sources.json"
