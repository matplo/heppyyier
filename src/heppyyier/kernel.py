import json
import os
import pathlib
import sys
import tempfile
from typing import Optional


def _check_deps() -> None:
    missing = []
    try:
        import ipykernel  # noqa: F401
    except ImportError:
        missing.append("ipykernel")
    try:
        import jupyter_client  # noqa: F401
    except ImportError:
        missing.append("jupyter_client")
    if missing:
        raise RuntimeError(
            f"Missing: {', '.join(missing)}. Run: pip install {' '.join(missing)}"
        )


def _build_env(packages_dir: pathlib.Path, packages: dict) -> dict:
    path_parts: list = []
    lib_parts: list = []
    pythonpath_parts: list = []

    for rec in packages.values():
        prefix = pathlib.Path(rec["prefix"])
        if (prefix / "bin").is_dir():
            path_parts.append(str(prefix / "bin"))
        if (prefix / "lib").is_dir():
            lib_parts.append(str(prefix / "lib"))
            for sp in sorted((prefix / "lib").glob("python*/site-packages")):
                pythonpath_parts.append(str(sp))

    def _prepend(parts: list, current: str) -> Optional[str]:
        if not parts:
            return None
        s = os.pathsep.join(parts)
        return s + os.pathsep + current if current else s

    env: dict = {"HEPPYYIER_PACKAGES_DIR": str(packages_dir)}

    v = _prepend(path_parts, os.environ.get("PATH", ""))
    if v:
        env["PATH"] = v

    # Both vars; kernel picks up whichever the OS honours
    v = _prepend(lib_parts, os.environ.get("DYLD_LIBRARY_PATH", ""))
    if v:
        env["DYLD_LIBRARY_PATH"] = v

    v = _prepend(lib_parts, os.environ.get("LD_LIBRARY_PATH", ""))
    if v:
        env["LD_LIBRARY_PATH"] = v

    v = _prepend(pythonpath_parts, os.environ.get("PYTHONPATH", ""))
    if v:
        env["PYTHONPATH"] = v

    return env


def install_kernel(
    name: Optional[str] = None,
    display_name: Optional[str] = None,
    user: bool = True,
) -> pathlib.Path:
    """Write a Jupyter kernel spec for the current heppyyier environment.

    Re-running overwrites the existing spec, refreshing env paths after new
    packages are installed.
    """
    _check_deps()

    from .config import get_packages_dir
    from .registry import get_registry

    packages = get_registry().all_packages()
    packages_dir = get_packages_dir()

    if name is None:
        name = "heppyyier-" + pathlib.Path(sys.prefix).name

    if display_name is None:
        pkg_list = ", ".join(sorted(packages.keys())) if packages else "no packages installed"
        display_name = f"HEP ({pkg_list})"

    env = _build_env(packages_dir, packages)

    kernel_spec = {
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": display_name,
        "language": "python",
        "env": env,
        "metadata": {
            "heppyyier": True,
            "packages_dir": str(packages_dir),
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        (tmppath / "kernel.json").write_text(json.dumps(kernel_spec, indent=2))

        from jupyter_client.kernelspec import KernelSpecManager
        dest = KernelSpecManager().install_kernel_spec(
            str(tmppath), kernel_name=name, user=user, replace=True
        )

    return pathlib.Path(dest)
