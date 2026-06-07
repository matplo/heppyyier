import pathlib
import sys

import click

from .config import get_build_dir, get_packages_dir, get_registry_path


@click.group()
@click.version_option(message="%(prog)s %(version)s")
def cli():
    """heppyyier — HEP C++ package manager with cppyy bindings."""


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("packages", nargs=-1, required=True)
@click.option("--version", "-v", default=None, help="Package version (single-package installs only).")
@click.option("--recipe", "recipe_path", default=None, help="Path to a YAML recipe file (single-package installs only).")
@click.option("--force", is_flag=True, help="Re-extract source and rebuild (keeps cached tarball).")
@click.option("--redownload", is_flag=True, help="Delete cached tarball and re-download before rebuilding.")
@click.option("--verbose", is_flag=True, help="Show build output in terminal.")
@click.option("--njobs", "-j", default=None, type=int, help="Override parallel make jobs (overrides recipe default of 4).")
def install(packages, version, recipe_path, force, redownload, verbose, njobs):
    """Download, build, and register one or more HEP C++ packages (in order)."""
    from .builder import build_package
    for i, package in enumerate(packages):
        # --version and --recipe only apply when a single package is given
        _version = version if len(packages) == 1 else None
        _recipe_path = recipe_path if len(packages) == 1 else None
        if len(packages) > 1:
            click.echo(f"\n[{i+1}/{len(packages)}] Installing {package} ...")
        build_package(package, version=_version, recipe_path=_recipe_path, force=force, redownload=redownload, verbose=verbose, njobs=njobs)


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
    """Create packages directory, registry skeleton, and check cppyy."""
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

    # Check cppyy backend and auto-fix — only when libCling is inside this venv.
    # Importing cppyy_backend on shared HPC environments (where libCling lives
    # outside the venv) triggers PCH rebuilds that can loop indefinitely on
    # network filesystems. Skip the check entirely in that case.
    from .cppyy_fix import is_in_venv, libcling_in_venv, _find_libcling
    if is_in_venv():
        lib = _find_libcling()
        if lib is None:
            click.echo("cppyy backend: not found (cppyy not installed?)")
        elif libcling_in_venv(lib):
            from .cppyy_fix import fix_cppyy, check_cppyy, get_broken_deps
            if check_cppyy():
                click.echo("cppyy backend: OK")
            else:
                broken = get_broken_deps(lib)
                click.echo(f"\ncppyy backend: {len(broken)} broken library path(s) in {lib}:")
                for p in broken:
                    click.echo(f"  {p}")
                click.echo("Auto-fixing (library is inside this venv) ...")
                fixed = fix_cppyy(verbose=True)
                if fixed:
                    click.echo(f"cppyy patched successfully ({len(fixed)} path(s) fixed).")
                else:
                    click.echo(
                        "Could not auto-fix (install_name_tool / patchelf missing?).\n"
                        "Run 'heppyyier fix-cppyy' to retry manually.",
                        err=True,
                    )
        else:
            click.echo("cppyy backend: skipping check (libCling is outside this venv — run 'heppyyier fix-cppyy' if needed)")
    else:
        click.echo("cppyy backend: skipping check (not in a virtual environment)")

    click.echo("\nRun 'heyy generate-modules' to enable 'module load' auto-loading.")


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
    "demo_pythia_fastjet_root.py",
    "demo_pythia_fastjet_root_cppyy.py",
    "demo_fjcontrib.ipynb",
    "demo_pythia_fastjet.ipynb",
    "demo_pythia_fastjet_root.ipynb",
    "demo_softdrop_splitting.ipynb",
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
# completion
# ---------------------------------------------------------------------------

_COMPLETION_ALIASES = ["heyy", "her", "heppyyier"]


def _bash_completion_script() -> str:
    """Generate a bash 3.2-compatible completion script from the Click command tree."""
    top_cmds = sorted(
        name for name in cli.commands.keys() if not name.startswith("_")
    )
    subcommand_map = {
        name: sorted(cmd.commands.keys())
        for name, cmd in cli.commands.items()
        if not name.startswith("_") and hasattr(cmd, "commands")
    }

    lines = [
        "# heppyyier bash completion — works with bash 3.2+",
        "# Add to ~/.bashrc:  eval \"$(heyy completion)\"",
        "",
        "_heppyyier_completion() {",
        "    local cur prev",
        "    COMPREPLY=()",
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        '    prev="${COMP_WORDS[COMP_CWORD-1]}"',
        "",
        f'    local top_cmds="{" ".join(top_cmds)}"',
        "",
        '    case "$prev" in',
    ]
    for group, subcmds in subcommand_map.items():
        lines.append(f'        {group})')
        lines.append(f'            COMPREPLY=( $(compgen -W "{" ".join(subcmds)}" -- "$cur") )')
        lines.append( '            return 0 ;;')
    lines += [
        '    esac',
        '',
        '    COMPREPLY=( $(compgen -W "$top_cmds" -- "$cur") )',
        '    return 0',
        '}',
        '',
    ]
    for alias in _COMPLETION_ALIASES:
        lines.append(f"complete -F _heppyyier_completion {alias}")
    return "\n".join(lines) + "\n"

@cli.command("completion")
@click.option(
    "--shell", "shell_type",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Shell type (default: auto-detected from $SHELL).",
)
def completion(shell_type):
    """Print shell completion setup lines for all heppyyier aliases.

    \b
    Bash / Zsh — add to ~/.bashrc or ~/.zshrc:
        eval "$(heyy completion)"

    \b
    Fish — add to ~/.config/fish/config.fish:
        heyy completion --shell fish | source
    """
    import os

    if shell_type is None:
        sh = os.environ.get("SHELL", "")
        if "zsh" in sh:
            shell_type = "zsh"
        elif "fish" in sh:
            shell_type = "fish"
        else:
            shell_type = "bash"

    if shell_type == "fish":
        for alias in _COMPLETION_ALIASES:
            var = f"_{alias.upper()}_COMPLETE"
            click.echo(f"env {var}=fish_source {alias} | source")
    elif shell_type == "bash":
        click.echo(_bash_completion_script())
    else:
        for alias in _COMPLETION_ALIASES:
            var = f"_{alias.upper()}_COMPLETE"
            click.echo(f'eval "$({var}=zsh_source {alias})"')


@cli.command("modules")
def modules():
    """Print 'module use <path>' for the heppyyier modulefiles directory.

    Usage: eval "$(heyy modules)"
    Then:  module load jewel/2.4.0
    """
    from .shell import get_modulefiles_dir
    click.echo(f"module use {get_modulefiles_dir()}")


@cli.command("generate-modules")
def generate_modules():
    """Regenerate TCL modulefiles for all installed packages."""
    from .shell import write_tcl_modulefile, get_modulefiles_dir, write_sitecustomize
    from .registry import get_registry
    reg = get_registry()
    count = 0
    for name, record in reg.all_packages().items():
        import pathlib
        mod_file = write_tcl_modulefile(name, record["version"], pathlib.Path(record["prefix"]))
        click.echo(f"  wrote {mod_file}")
        count += 1
    if count == 0:
        click.echo("No installed packages found.")
    else:
        click.echo(f"\nModulefiles at: {get_modulefiles_dir()}")
        click.echo(f'Add to your shell:  eval "$(heyy modules)"')
    sc = write_sitecustomize()
    click.echo(f"sitecustomize.py refreshed: {sc}")


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

_HEPPYYIER_GITHUB = "git+https://github.com/matplo/heppyyier.git"

@cli.command()
def upgrade():
    """Reinstall heppyyier itself from GitHub (picks up latest commits)."""
    import shutil
    import subprocess

    pip = pathlib.Path(sys.executable).parent / "pip"
    uv = shutil.which("uv")

    if uv:
        cmd = [uv, "pip", "install", "--reinstall-package", "heppyyier", _HEPPYYIER_GITHUB]
    else:
        cmd = [str(pip), "install", "--force-reinstall", "--no-deps", _HEPPYYIER_GITHUB]

    click.echo(f"Upgrading heppyyier from GitHub ...")
    click.echo(f"  {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        click.echo("Done. Restart your shell or re-enter the henv subshell to use the new version.")
    else:
        click.echo("Upgrade failed — check the output above.", err=True)
        sys.exit(result.returncode)


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


# ---------------------------------------------------------------------------
# kernel subgroup
# ---------------------------------------------------------------------------

@cli.group()
def kernel():
    """Manage Jupyter kernel registrations."""


@kernel.command("install")
@click.option("--name", default=None, help="Kernel name (default: heppyyier-<venv-name>).")
@click.option("--display-name", "display_name", default=None,
              help="Display name shown in JupyterHub/Lab (default: 'HEP (<pkg list>)').")
@click.option("--sys-prefix", "sys_prefix", is_flag=True, default=False,
              help="Install into sys.prefix instead of the user's home directory.")
def kernel_install(name, display_name, sys_prefix):
    """Register a Jupyter kernel for the current heppyyier environment.

    The kernel spec embeds PATH, library paths, and PYTHONPATH for every
    installed package, so notebooks work without any manual setup.

    Re-run after installing new packages to refresh the kernel's environment.
    """
    from .kernel import install_kernel
    try:
        dest = install_kernel(name=name, display_name=display_name, user=not sys_prefix)
    except RuntimeError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    # Read back kernel.json to report what was embedded
    import json
    spec = json.loads((dest / "kernel.json").read_text())
    click.echo(f"Kernel installed: {dest}")
    click.echo(f"  display name : {spec['display_name']}")
    click.echo(f"  python       : {spec['argv'][0]}")
    env = spec.get("env", {})
    if "HEPPYYIER_PACKAGES_DIR" in env:
        click.echo(f"  packages dir : {env['HEPPYYIER_PACKAGES_DIR']}")
    if "PATH" in env:
        click.echo(f"  PATH         : {env['PATH'][:80]}{'...' if len(env['PATH']) > 80 else ''}")
    click.echo(f"\nSelect '{spec['display_name']}' in JupyterHub/Lab to use it.")


# ---------------------------------------------------------------------------
# Entry point — clean error messages, no tracebacks for known exceptions
# ---------------------------------------------------------------------------

def main():
    from .exceptions import RecipeNotFoundError, BuildError, PackageNotInstalledError
    try:
        rv = cli(standalone_mode=False)
        sys.exit(rv or 0)
    except (RecipeNotFoundError, BuildError, PackageNotInstalledError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except click.exceptions.Abort:
        sys.exit(1)
    except click.exceptions.Exit as exc:
        sys.exit(exc.exit_code)
    except click.exceptions.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
