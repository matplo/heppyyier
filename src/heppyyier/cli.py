import pathlib
import sys

import click

from .config import get_build_dir, get_packages_dir, get_registry_path


@click.group()
def cli():
    """heppyyier — HEP C++ package manager with cppyy bindings."""


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("package")
@click.option("--version", "-v", default=None, help="Package version to install.")
@click.option("--recipe", "recipe_path", default=None, help="Path to a YAML recipe file.")
@click.option("--force", is_flag=True, help="Re-extract source and rebuild (keeps cached tarball).")
@click.option("--redownload", is_flag=True, help="Delete cached tarball and re-download before rebuilding.")
@click.option("--verbose", is_flag=True, help="Show build output in terminal.")
def install(package, version, recipe_path, force, redownload, verbose):
    """Download, build, and register a HEP C++ package."""
    from .builder import build_package
    build_package(package, version=version, recipe_path=recipe_path, force=force, redownload=redownload, verbose=verbose)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("package")
@click.option("--prefix", required=True, help="Path to the installed package prefix.")
@click.option("--recipe", "recipe_path", default=None, help="Path to a YAML recipe file.")
@click.option("--version", "-v", default=None, help="Version string (overrides recipe default).")
def register(package, prefix, recipe_path, version):
    """Register a pre-built package (no compilation)."""
    from .builder import register_package
    register_package(package, prefix, recipe_path=recipe_path, version=version)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@cli.command(name="list")
def list_cmd():
    """Show all installed packages."""
    from .registry import get_registry
    reg = get_registry()
    pkgs = reg.all_packages()
    if not pkgs:
        click.echo("No packages installed. Run 'heppyyier install <pkg>'.")
        return
    click.echo(f"{'Package':<20} {'Version':<12} Prefix")
    click.echo("-" * 70)
    for name, rec in pkgs.items():
        click.echo(f"{name:<20} {rec.get('version','?'):<12} {rec.get('prefix','?')}")


# ---------------------------------------------------------------------------
# avail
# ---------------------------------------------------------------------------

@cli.command()
def avail():
    """Show all available recipes (built-in + remote sources)."""
    from .recipe import list_builtin_recipes
    from .recipe_sources import list_all_remote_recipes

    click.echo("Built-in recipes:")
    for name, ver in list_builtin_recipes():
        click.echo(f"  {name}/{ver}")

    remote = list_all_remote_recipes()
    if remote:
        click.echo("\nRemote recipes:")
        for name, ver, src in remote:
            click.echo(f"  {name}/{ver}  [{src}]")


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("package")
def info(package):
    """Show details for an installed package."""
    from .registry import get_registry
    rec = get_registry().get(package)
    if rec is None:
        click.echo(f"Package '{package}' is not installed.", err=True)
        sys.exit(1)
    for key, val in rec.items():
        if isinstance(val, list):
            click.echo(f"{key}:")
            for item in val:
                click.echo(f"  - {item}")
        else:
            click.echo(f"{key}: {val}")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@cli.command()
def init():
    """Create packages directory, registry skeleton, and fix cppyy if needed."""
    pkg_dir = get_packages_dir()
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "logs").mkdir(exist_ok=True)
    (pkg_dir / "src").mkdir(exist_ok=True)
    reg_path = get_registry_path()
    if not reg_path.exists():
        import json
        reg_path.write_text(json.dumps({"schema_version": 1, "packages": {}}, indent=2))
        click.echo(f"Created registry: {reg_path}")
    else:
        click.echo(f"Registry already exists: {reg_path}")
    click.echo(f"Packages directory: {pkg_dir}")

    # Auto-register the canonical heppyyier-recipes repo if not already present
    _RECIPES_REPO = "https://github.com/matplo/heppyyier-recipes"
    from .recipe_sources import list_sources, add_source
    existing_urls = {s["url"] for s in list_sources()}
    if _RECIPES_REPO not in existing_urls:
        click.echo(f"\nFetching recipes from {_RECIPES_REPO} ...")
        try:
            add_source(_RECIPES_REPO)
        except Exception as exc:
            click.echo(f"  Warning: could not fetch recipes ({exc}). Run 'heppyyier recipe update' later.", err=True)
    else:
        click.echo("Recipe source: already registered")

    # Auto-fix cppyy backend broken rpaths (common on macOS with Homebrew vs MacPorts)
    from .cppyy_fix import fix_cppyy, check_cppyy
    if not check_cppyy():
        click.echo("\nDetected broken cppyy backend — attempting auto-fix ...")
        fixed = fix_cppyy(verbose=True)
        if fixed:
            click.echo(f"cppyy patched successfully ({len(fixed)} path(s) fixed).")
        else:
            click.echo(
                "Could not auto-fix cppyy. Run 'heppyyier fix-cppyy' for details.",
                err=True,
            )
    else:
        click.echo("cppyy backend: OK")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@cli.command("config")
def config_cmd():
    """Show active configuration (packages directory, registry, etc.)."""
    import os
    from .config import get_packages_dir, get_registry_path, get_log_dir

    pkg_dir = get_packages_dir()
    click.echo(f"packages_dir : {pkg_dir}")
    click.echo(f"registry     : {get_registry_path()}")
    click.echo(f"log_dir      : {get_log_dir()}")
    click.echo(f"src_dir      : {pkg_dir / 'src'}")
    # Show which config source was used
    if "HEPPYYIER_PACKAGES_DIR" in os.environ:
        click.echo("(source: HEPPYYIER_PACKAGES_DIR env var)")
    elif "HEPPYYIER_BUILD_DIR" in os.environ:
        click.echo("(source: HEPPYYIER_BUILD_DIR env var  [legacy])")
    elif (pathlib.Path.cwd() / ".heppyyier.toml").exists():
        click.echo("(source: .heppyyier.toml)")
    else:
        import sys
        if sys.prefix != sys.base_prefix:
            click.echo(f"(source: active venv  {sys.prefix})")
        else:
            click.echo("(source: default  ./packages/)")


# ---------------------------------------------------------------------------
# fix-cppyy
# ---------------------------------------------------------------------------

@cli.command("fix-cppyy")
@click.option("--check", is_flag=True, help="Only check, do not patch.")
def fix_cppyy_cmd(check):
    """Detect and fix broken rpath entries in the cppyy backend (macOS)."""
    from .cppyy_fix import fix_cppyy, check_cppyy, _find_libcling, get_broken_deps
    lib = _find_libcling()
    if lib is None:
        click.echo("cppyy backend not found (is cppyy installed?).", err=True)
        sys.exit(1)
    click.echo(f"Backend: {lib}")
    broken = get_broken_deps(lib)
    if not broken:
        click.echo("All library paths are healthy — nothing to fix.")
        return
    click.echo(f"Found {len(broken)} broken path(s):")
    for p in broken:
        click.echo(f"  {p}")
    if check:
        return
    fixed = fix_cppyy(verbose=True)
    if fixed:
        click.echo(f"\ncppyy patched successfully ({len(fixed)} path(s) fixed).")
    else:
        click.echo("\nCould not fix all paths. Install missing libraries manually.", err=True)


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("package", required=False)
def env(package):
    """Print shell environment variables for a package (or all loaded)."""
    from .registry import get_registry
    reg = get_registry()
    targets = [package] if package else list(reg.all_packages().keys())
    for name in targets:
        rec = reg.get(name)
        if rec is None:
            continue
        prefix = rec["prefix"]
        NAME = name.upper().replace("-", "_")
        click.echo(f"export {NAME}_DIR={prefix!r}")
        click.echo(f"export PATH={prefix!r}/bin:$PATH")


# ---------------------------------------------------------------------------
# demos
# ---------------------------------------------------------------------------

_DEMOS_BASE = "https://raw.githubusercontent.com/matplo/heppyyier/main/demos"
_DEMO_FILES = [
    "demo_fastjet.py",
    "demo_fjcontrib.py",
    "demo_pythia_fastjet.py",
    "demo_fjcontrib.ipynb",
    "demo_pythia_fastjet.ipynb",
]

@cli.command()
@click.option("--dest", default="./heppyyier_demos", show_default=True, help="Directory to download demos into.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files.")
def demos(dest, overwrite):
    """Download demo scripts from GitHub to the current directory."""
    import requests
    dest_path = pathlib.Path(dest).resolve()
    dest_path.mkdir(parents=True, exist_ok=True)
    for fname in _DEMO_FILES:
        out = dest_path / fname
        if out.exists() and not overwrite:
            click.echo(f"  skip  {fname}  (already exists, use --overwrite)")
            continue
        url = f"{_DEMOS_BASE}/{fname}"
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            out.write_bytes(r.content)
            click.echo(f"  ok    {fname}")
        else:
            click.echo(f"  fail  {fname}  (HTTP {r.status_code})", err=True)
    click.echo(f"\nDemos written to: {dest_path}")
    click.echo("Run: python demo_fastjet.py")


# ---------------------------------------------------------------------------
# shell-init
# ---------------------------------------------------------------------------

@cli.command("shell-init")
def shell_init():
    """Print shell function definition for eval (enables module load/unload)."""
    from .shell import shell_init_script
    click.echo(shell_init_script(), nl=False)


# ---------------------------------------------------------------------------
# _shell-env-path  (internal, called by the shell `module` function)
# ---------------------------------------------------------------------------

@cli.command("_shell-env-path", hidden=True)
@click.argument("name")
@click.argument("version", required=False, default=None)
def shell_env_path(name, version):
    """Internal: print prefix path for a package (used by shell module function)."""
    from .shell import env_path
    from .exceptions import PackageNotInstalledError
    try:
        p = env_path(name, version or None)
        click.echo(str(p))
    except PackageNotInstalledError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# _shell-list  (internal)
# ---------------------------------------------------------------------------

@cli.command("_shell-list", hidden=True)
def shell_list():
    """Internal: list shell-loaded packages from env vars."""
    from .shell import list_loaded
    loaded = list_loaded()
    if not loaded:
        click.echo("No packages currently loaded.")
    else:
        for name, version in loaded:
            click.echo(f"{name}/{version}")


# ---------------------------------------------------------------------------
# recipe subgroup
# ---------------------------------------------------------------------------

@cli.group()
def recipe():
    """Manage remote recipe sources."""


@recipe.command("add")
@click.argument("url")
def recipe_add(url):
    """Add a GitHub repo/directory as a recipe source."""
    from .recipe_sources import add_source
    add_source(url)


@recipe.command("remove")
@click.argument("url")
def recipe_remove(url):
    """Remove a recipe source."""
    from .recipe_sources import remove_source
    remove_source(url)


@recipe.command("list-sources")
def recipe_list_sources():
    """List all registered remote recipe sources."""
    from .recipe_sources import list_sources
    sources = list_sources()
    if not sources:
        click.echo("No remote sources registered. Use 'heppyyier recipe add <url>'.")
        return
    for src in sources:
        subtree = f"  subtree: {src['subtree']}" if src.get("subtree") else ""
        click.echo(f"  {src['url']}{subtree}")
        click.echo(f"    added: {src['added_at']}")
        click.echo(f"    local: {src['local_path']}")


@recipe.command("update")
def recipe_update():
    """Update all remote recipe sources (git pull)."""
    from .recipe_sources import update_sources
    update_sources()
