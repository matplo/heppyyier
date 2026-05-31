import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Optional

import requests
from tqdm import tqdm

from .config import get_build_dir, get_log_dir
from .exceptions import BuildError
from .recipe import Recipe
from .shell import generate_env_scripts


class PackageBuilder:
    def __init__(self, recipe: Recipe, verbose: bool = False):
        self.recipe = recipe
        self.verbose = verbose
        self._build_dir = get_build_dir()
        self._log_dir = get_log_dir()

    def build(self, version: Optional[str] = None, force: bool = False, redownload: bool = False) -> dict:
        version = version or self.recipe.version
        prefix = (self._build_dir / self.recipe.name / version).resolve()
        prefix.mkdir(parents=True, exist_ok=True)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        log_path = self._log_dir / f"{self.recipe.name}-{version}-build.log"

        print(f"Building {self.recipe.name} {version} → {prefix}")
        print(f"Log: {log_path}")

        src_dir = self._download_and_extract(version, force=force, redownload=redownload)

        if self.recipe.build_script:
            self._run_custom_script(src_dir, prefix, version, log_path)
        elif self.recipe.build_system == "autotools":
            build_dir = self._configure_autotools(src_dir, prefix, log_path)
            self._make(build_dir, log_path)
            self._install(build_dir, log_path)
        elif self.recipe.build_system == "cmake":
            build_dir = self._configure_cmake(src_dir, prefix, log_path)
            self._make(build_dir, log_path)
            self._install(build_dir, log_path)
        else:
            raise BuildError(f"Unknown build_system: {self.recipe.build_system}")

        self._verify(prefix)
        generate_env_scripts(self.recipe.name, version, prefix)
        return self._make_registry_record(prefix, version, log_path)

    def _base_env(self) -> dict:
        env = os.environ.copy()
        env["CXX"] = env.get("CXX", "c++")
        env["CC"] = env.get("CC", "cc")
        if sys.platform == "darwin":
            if "MACOSX_DEPLOYMENT_TARGET" not in env:
                ver = platform.mac_ver()[0]
                major_minor = ".".join(ver.split(".")[:2]) if ver else "11.0"
                env["MACOSX_DEPLOYMENT_TARGET"] = major_minor
        # Avoid conda/ROOT interference
        for key in ("CONDA_PREFIX", "ROOT_PATH", "ROOTSYS"):
            env.pop(key, None)
        return env

    def _download_and_extract(self, version: str, force: bool = False, redownload: bool = False) -> pathlib.Path:
        url = self.recipe.resolved_url(version=version)
        src_base = self._build_dir / "src"
        src_base.mkdir(parents=True, exist_ok=True)

        # Handle HepForge-style query-string URLs: .../downloads/?f=Pkg-1.0.tar.gz
        _last = url.split("/")[-1]
        if _last.startswith("?"):
            from urllib.parse import parse_qs
            _params = parse_qs(_last[1:])
            filename = _params.get("f", [_last])[0]
        else:
            filename = _last
        dest = src_base / filename
        extract_dir = src_base / f"{self.recipe.name}-{version}-src"

        if redownload and dest.exists():
            print(f"Removing cached tarball: {dest.name}")
            dest.unlink()

        if force and extract_dir.exists():
            print(f"Removing cached source tree: {extract_dir.name}")
            shutil.rmtree(extract_dir)

        if not dest.exists():
            print(f"Downloading {url} ...")
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            tmp_dest = dest.with_suffix(dest.suffix + ".part")
            try:
                with open(tmp_dest, "wb") as f, tqdm(
                    total=total, unit="B", unit_scale=True, desc=filename
                ) as bar:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        bar.update(len(chunk))
                tmp_dest.rename(dest)
            except Exception:
                tmp_dest.unlink(missing_ok=True)
                raise
        else:
            print(f"Using cached tarball: {dest}")

        if not extract_dir.exists():
            print(f"Extracting {dest.name} ...")
            try:
                with tarfile.open(dest) as tf:
                    tf.extractall(src_base)
                    members = tf.getnames()
                    top = members[0].split("/")[0]
                    extracted = src_base / top
                    if extracted != extract_dir:
                        extracted.rename(extract_dir)
            except (tarfile.TarError, Exception) as exc:
                dest.unlink(missing_ok=True)
                raise BuildError(
                    f"Failed to extract {dest.name} (file may be corrupt): {exc}\n"
                    "Re-run with --force to download a fresh copy."
                ) from exc

        return extract_dir

    def _run(self, cmd: list, cwd: pathlib.Path, log_path: pathlib.Path) -> None:
        mode = "a"
        with open(log_path, mode) as log:
            log.write(f"\n$ {' '.join(str(c) for c in cmd)}\n")
            log.flush()
            if self.verbose:
                proc = subprocess.run(
                    cmd, cwd=cwd, env=self._base_env(), check=False
                )
            else:
                proc = subprocess.run(
                    cmd,
                    cwd=cwd,
                    env=self._base_env(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
        if proc.returncode != 0:
            raise BuildError(
                f"Command failed (exit {proc.returncode}): {' '.join(str(c) for c in cmd)}\n"
                f"See log: {log_path}"
            )

    def _configure_autotools(
        self, src_dir: pathlib.Path, prefix: pathlib.Path, log_path: pathlib.Path
    ) -> pathlib.Path:
        configure = src_dir / "configure"
        if not configure.exists():
            raise BuildError(f"No configure script found in {src_dir}")
        cmd = [str(configure), f"--prefix={prefix}"] + self.recipe.configure_args
        print(f"Configuring (autotools) ...")
        self._run(cmd, src_dir, log_path)
        return src_dir

    def _configure_cmake(
        self, src_dir: pathlib.Path, prefix: pathlib.Path, log_path: pathlib.Path
    ) -> pathlib.Path:
        build_dir = src_dir.parent / f"{src_dir.name}-cmake-build"
        build_dir.mkdir(exist_ok=True)
        cmd = [
            "cmake",
            str(src_dir),
            f"-DCMAKE_INSTALL_PREFIX={prefix}",
        ] + self.recipe.configure_args
        print(f"Configuring (cmake) ...")
        self._run(cmd, build_dir, log_path)
        return build_dir

    def _make(self, build_dir: pathlib.Path, log_path: pathlib.Path) -> None:
        print(f"Building (make -j{self.recipe.make_jobs}) ...")
        self._run(["make", f"-j{self.recipe.make_jobs}"], build_dir, log_path)

    def _install(self, build_dir: pathlib.Path, log_path: pathlib.Path) -> None:
        print("Installing ...")
        self._run(["make", "install"], build_dir, log_path)

    def _run_custom_script(
        self,
        src_dir: pathlib.Path,
        prefix: pathlib.Path,
        version: str,
        log_path: pathlib.Path,
    ) -> None:
        from .registry import get_registry

        configure_args_str = " ".join(self.recipe.configure_args)
        env = self._base_env()

        # Inject {name}_prefix for every package in the registry, not just
        # depends_on — this lets build scripts use optional packages via shell
        # conditionals without declaring a hard dependency.
        pkg_vars: dict = {}
        for pkg_name, rec in get_registry().all_packages().items():
            pkg_vars[f"{pkg_name}_prefix"] = rec["prefix"]

        class _Default(dict):
            """Return empty string for any key not in the dict."""
            def __missing__(self, key: str) -> str:
                return ""

        fmt = _Default(
            prefix=prefix,
            version=version,
            srcdir=src_dir,
            builddir=src_dir,
            n_cores=self.recipe.make_jobs,
            configure_args=configure_args_str,
            CXX=env.get("CXX", "c++"),
            CC=env.get("CC", "cc"),
            **pkg_vars,
        )
        script = self.recipe.build_script.format_map(fmt)
        print("Running custom build script ...")
        self._run(["bash", "-c", script], src_dir, log_path)

    def _verify(self, prefix: pathlib.Path) -> None:
        if self.recipe.verify_binary:
            binary = prefix / "bin" / self.recipe.verify_binary
            if not binary.exists():
                raise BuildError(
                    f"Verification failed: {binary} not found after install"
                )
        lib_dir = prefix / "lib"
        if not any(lib_dir.glob("lib*")):
            raise BuildError(
                f"Verification failed: no libraries found in {lib_dir}"
            )
        print("Verification passed.")

    def _make_registry_record(
        self, prefix: pathlib.Path, version: str, log_path: pathlib.Path
    ) -> dict:
        builtin_dir = pathlib.Path(__file__).parent / "recipes"
        src = self.recipe.source_path
        recipe_path = (
            str(src) if src and not str(src).startswith(str(builtin_dir)) else None
        )
        return {
            "version": version,
            "prefix": str(prefix),
            "include_dir": str(prefix / "include"),
            "lib_dir": str(prefix / "lib"),
            "depends_on": self.recipe.depends_on,
            "build_log": str(log_path),
            "recipe_path": recipe_path,
        }


def build_package(
    name: str,
    version: Optional[str] = None,
    recipe_path: Optional[str] = None,
    force: bool = False,
    redownload: bool = False,
    verbose: bool = False,
) -> dict:
    from .recipe import find_recipe
    from .registry import get_registry

    recipe = find_recipe(name, version=version, recipe_path=recipe_path)
    reg = get_registry()

    if reg.is_installed(recipe.name) and not force:
        existing = reg.get(recipe.name)
        print(
            f"{recipe.name} {existing['version']} already installed. "
            "Use --force to rebuild."
        )
        return existing

    builder = PackageBuilder(recipe, verbose=verbose)
    record = builder.build(version=version or recipe.version, force=force, redownload=redownload)
    reg.register(recipe.name, record)
    print(f"\n{recipe.name} {record['version']} installed at {record['prefix']}")
    return record


def register_package(
    name: str,
    prefix: str,
    recipe_path: Optional[str] = None,
    version: Optional[str] = None,
) -> dict:
    from .recipe import find_recipe
    from .registry import get_registry
    from .shell import generate_env_scripts

    recipe = find_recipe(name, version=version, recipe_path=recipe_path)
    prefix_path = pathlib.Path(prefix).resolve()

    if not prefix_path.is_dir():
        raise BuildError(f"Prefix directory does not exist: {prefix_path}")

    ver = version or recipe.version
    builtin_dir = pathlib.Path(__file__).parent / "recipes"
    src = recipe.source_path
    stored_recipe_path = (
        str(src) if src and not str(src).startswith(str(builtin_dir)) else None
    )
    record = {
        "version": ver,
        "prefix": str(prefix_path),
        "include_dir": str(prefix_path / "include"),
        "lib_dir": str(prefix_path / "lib"),
        "depends_on": recipe.depends_on,
        "build_log": None,
        "recipe_path": stored_recipe_path,
    }

    generate_env_scripts(recipe.name, ver, prefix_path)
    get_registry().register(recipe.name, record)
    print(f"Registered {recipe.name} {ver} from {prefix_path}")
    return record
