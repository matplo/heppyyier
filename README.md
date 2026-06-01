# heppyyier

A local HEP C++ package manager that downloads, compiles, and exposes packages as Python
modules via [cppyy](https://cppyy.readthedocs.io/) — no ROOT, no conda, no system-wide
installs required.

Supported packages out of the box: **FastJet**, **Pythia8**, **HepMC3**, **fjcontrib**, **LHAPDF6**.

---

## Requirements

- Python 3.9+ in a virtual environment (strongly recommended)
- A C++ compiler: `clang++` (macOS) or `g++` (Linux)
- `cmake` (for HepMC3)
- `swig` (for LHAPDF Python bindings — optional but recommended)
- Internet access for first-time package downloads

On macOS with Homebrew:
```bash
brew install cmake swig
```

---

## Installation

Create and activate a virtual environment, then install heppyyier:

> **Short aliases:** `heyy` and `her` are registered as identical entry points alongside
> `heppyyier` — use whichever you prefer.
> ```bash
> heyy install fastjet
> her list
> heppyyier config   # all three are the same CLI
> ```

```bash
python -m venv myenv
source myenv/bin/activate

# From PyPI (once published):
pip install heppyyier

# Or directly from GitHub (no clone needed):
pip install git+https://github.com/matplo/heppyyier.git

# To update to the latest version:
pip install --upgrade git+https://github.com/matplo/heppyyier.git
# If pip skips the update (version string unchanged), force it:
pip install --force-reinstall git+https://github.com/matplo/heppyyier.git

# Or from a local clone (editable install for development):
git clone https://github.com/matplo/heppyyier
cd heppyyier
pip install -e .
```

---

## Initialise

Run once after installation to create the package store, fetch recipes, and check cppyy:

```bash
heppyyier init
```

This creates the package store under your active venv and automatically clones the
[heppyyier-recipes](https://github.com/matplo/heppyyier-recipes) repository so the
latest recipes are always available:

```
<venv>/heppyyier_packages/
  registry.json       ← installed package index
  src/                ← cached tarballs (safe to delete to free space)
  logs/               ← build logs
  recipe-cache/       ← cloned recipe repos
  recipe-sources.json ← registered recipe sources
```

`init` also checks whether the cppyy backend (`libCling`) has broken library references
(common on macOS when the cppyy wheel was built against a different package manager).
If broken paths are found they are reported but **never patched automatically**.
To apply the fix:

```bash
# Inspect first:
heppyyier fix-cppyy --check

# Then patch:
heppyyier fix-cppyy

# Or patch in one step at init time:
heppyyier init --fix-cppyy
```

To refresh recipes at any time (e.g. after a new recipe is added upstream):
```bash
heppyyier recipe update
```

Check where your packages will be installed:
```bash
heppyyier config
```

Override the location at any time:
```bash
# Environment variable (shell session)
export HEPPYYIER_PACKAGES_DIR=/opt/hep/packages

# Or permanently in .heppyyier.toml at your project root:
# packages_dir = "/opt/hep/packages"
```

---

## Installing packages

### Recommended install order

Install order matters for Pythia8: it is built with optional support for FastJet, HepMC3,
and LHAPDF6 **only if those packages are already present in the registry at configure time**.
No explicit dependency is declared — if a package is installed, Pythia8 picks it up
automatically; if not, that interface is simply omitted.

You can pass multiple package names to `install` and they are built **sequentially in the
order given** — which is all that is needed to satisfy the implicit Pythia8 dependencies:

```bash
heppyyier install fastjet hepmc3 lhapdf pythia8 fjcontrib
```

Or one at a time:

```bash
heppyyier install fastjet           # (1) jet finding
heppyyier install hepmc3            # (2) event record I/O
heppyyier install lhapdf            # (3) PDF sets
heppyyier install pythia8           # (4) sees fastjet + hepmc3 + lhapdf → adds --with-* flags
heppyyier install fjcontrib         # (5) jet substructure (hard-requires fastjet)
```

During the Pythia8 build you will see which packages were detected:
```
[pythia8] FastJet : .../heppyyier_packages/fastjet/3.5.1
[pythia8] HepMC3  : .../heppyyier_packages/hepmc3/3.3.1
[pythia8] LHAPDF6 : .../heppyyier_packages/lhapdf/6.5.4
[pythia8] configure: --with-fastjet3=... --with-hepmc3=... --with-lhapdf6=...
```

### Version precedence

The registry stores **one active entry per package name** — the last-installed version.
If you install fastjet 3.4 and then fastjet 3.5, only 3.5 is visible to subsequent builds.
To control which version Pythia8 sees, install (or `register`) the desired fastjet version
**before** running `heppyyier install pythia8`.

### Useful flags

```bash
heppyyier install fastjet --verbose          # show build output live
heppyyier install fastjet --force            # re-extract and rebuild (keeps cached tarball)
heppyyier install fastjet --redownload       # delete tarball and start completely fresh

# Flags apply to all packages when multiple names are given:
heppyyier install fastjet hepmc3 lhapdf pythia8 fjcontrib --verbose

# --version and --recipe only take effect for a single-package install:
heppyyier install fastjet --version 3.4.2
heppyyier install mypackage --recipe /path/to/mypackage/1.0.yaml
```

### Inspecting what is installed

```bash
heppyyier list               # all installed packages with versions and prefixes
heppyyier info fastjet       # full details for one package
```

---

## Using packages in Python

### Loading with heppyyier

```python
import heppyyier

heppyyier.load("fastjet")
heppyyier.load("pythia8")
heppyyier.load("fjcontrib")   # loads fastjet first automatically

# Packages are now available as top-level modules via cppyy proxy:
import fastjet
jet = fastjet.PseudoJet(1.0, 0.0, 1.0, 1.414)
print(jet.pt())

# Or directly via cppyy.gbl:
import cppyy
cppyy.gbl.fastjet.PseudoJet(1.0, 0.0, 1.0, 1.414)
```

### LHAPDF — native Python bindings

LHAPDF is built with SWIG Python bindings. After `heppyyier install lhapdf` the module
is installed directly into your venv — **no `heppyyier.load()` needed**:

```python
import lhapdf                          # works straight away
pdf = lhapdf.mkPDF("CT10nlo", 0)
xg  = pdf.xfxQ(21, 0.01, 91.2)        # gluon PDF at x=0.01, Q=91.2 GeV
print(f"xg(x=0.01, Q=Mz) = {xg:.4f}")
```

For C++ interop (passing `LHAPDF::PDF*` to other cppyy-loaded code):

```python
heppyyier.load("lhapdf")               # loads the C++ library via cppyy
import cppyy
pdf = cppyy.gbl.LHAPDF.mkPDF("CT10nlo", 0)
```

---

## Installing LHAPDF PDF sets

LHAPDF ships no PDF sets by default. Load the package first so `lhapdf` is on
your PATH, then install sets by name:

```bash
module load lhapdf

lhapdf install CT10nlo
lhapdf install NNPDF31_nnlo_as_0118
lhapdf install CT18NLO

lhapdf list --installed   # what is already downloaded
```

PDF data files are stored under:
```
<packages_dir>/lhapdf/6.5.4/share/LHAPDF/<SetName>/
```

Add that directory to `LHAPDF_DATA_PATH` if you keep PDF sets elsewhere:
```bash
export LHAPDF_DATA_PATH=/data/pdfsets:$LHAPDF_DATA_PATH
```

> **Without `module load`:** use the full path directly:
> ```bash
> $(heppyyier info lhapdf | awk '/^prefix/{print $2}')/bin/lhapdf install CT10nlo
> ```

---

## Shell module system

### heppyyier shell function (no Lmod required)

Optionally set up a `module` shell function:

```bash
# Add to ~/.zshrc or ~/.bashrc:
eval "$(heppyyier shell-init)"
```

Then in new shells:
```bash
module load fastjet          # sets FASTJET_DIR, PATH, LD_LIBRARY_PATH, …
module load fastjet/3.5.1    # specific version
module unload fastjet
module list                  # what is currently loaded
module avail                 # all installed packages
```

Python respects what is loaded at the shell level — if `HEPPYYIER_LOADED_FASTJET` is set,
`heppyyier.load("fastjet")` uses that version without touching the registry.

### TCL modulefiles (Lmod / Environment Modules)

If your site uses Lmod or Environment Modules, heppyyier can generate standard TCL
modulefiles for all installed packages:

```bash
heppyyier generate-modules        # write/refresh modulefiles for all installed packages
```

Modulefiles are written to `<packages_dir>/modulefiles/<name>/<version>` and include
`PATH`, `LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH`, `PYTHONPATH` (for packages with Python
bindings), and `CPATH`. Re-run after installing new packages to keep them up to date.

To add the directory to your active module search path:

```bash
eval "$(heppyyier modules)"       # runs: module use <packages_dir>/modulefiles
```

After that, standard `module` commands work as usual:

```bash
module load lhapdf/6.5.5
module load jewel/2.4.0
module list
```

> **Tip:** add `eval "$(heppyyier modules)"` to your `~/.bashrc` / `~/.zshrc` so the
> modulefiles directory is always in the search path.

---

## Examples

Demo scripts live in the `demos/` directory:

| Script | What it shows |
|--------|---------------|
| `demos/demo_fjcontrib.py` | SoftDrop, Nsubjettiness τ₂₁, EnergyCorrelator C₂ on Pythia8 dijets |
| `demos/demo_fjcontrib.ipynb` | Same as above in a Jupyter notebook with per-jet inspector table |
| `demos/demo_fastjet.py` | Basic FastJet jet finding |
| `demos/demo_pythia_fastjet.py` | Pythia8 + FastJet combined example |

Run:
```bash
heppyyier install fastjet pythia8 fjcontrib   # first time only
python demos/demo_fjcontrib.py
```

For Jupyter / JupyterHub:
```bash
pip install jupyter matplotlib numpy ipykernel
heppyyier kernel install          # register the venv as a selectable kernel
jupyter notebook demos/demo_fjcontrib.ipynb
```

Select the `HEP (...)` kernel when prompted, or use `--kernel heppyyier-<venv>` on the
command line. See the [Jupyter kernel](#jupyter-kernel) section for full options.

---

## Jupyter kernel

Register the current venv as a Jupyter kernel so it can be selected in JupyterHub or JupyterLab:

```bash
pip install ipykernel          # once, if not already installed
heppyyier kernel install
```

The kernel spec embeds `PATH`, `DYLD_LIBRARY_PATH`/`LD_LIBRARY_PATH`, `PYTHONPATH`, and
`HEPPYYIER_PACKAGES_DIR` for every installed package, so notebooks can immediately do:

```python
import heppyyier
heppyyier.load("fastjet")

import lhapdf          # works directly — PYTHONPATH is already set
```

Options:

```bash
heppyyier kernel install --name my-hep-env          # custom kernel name
heppyyier kernel install --display-name "HEP 2026"  # custom label in JupyterHub
heppyyier kernel install --sys-prefix               # install into sys.prefix (shared hub)
```

After installing new packages, re-run `heppyyier kernel install` (same `--name`) to refresh
the embedded paths — the existing spec is replaced in place.

---

## Registering externally-built packages

If you already have a package built by another tool (e.g. [yasp](https://github.com/matplo/yasp)):

```bash
heppyyier register fastjet --prefix /path/to/fastjet/3.5.1
heppyyier register fastjet --prefix /path/to/fastjet/3.5.1 --version 3.5.1
```

---

## External recipe sources

heppyyier ships built-in recipes for FastJet, HepMC3, LHAPDF6, Pythia8, and fjcontrib.
You can extend this with recipes from a GitHub repository or use a one-off recipe file
from anywhere on disk.

### GitHub recipe source

The [matplo/heppyyier-recipes](https://github.com/matplo/heppyyier-recipes) repository
is registered automatically by `heppyyier init`. You can add further repos the same way:

Point heppyyier at a GitHub repo and it will clone it locally and search it automatically
on every `install` and `avail` call:

```bash
# Whole repo (recipes expected at <name>/<version>.yaml under the root)
heppyyier recipe add https://github.com/user/my-hep-recipes

# Subdirectory of a repo
heppyyier recipe add https://github.com/matplo/yasp/tree/main/recipes
```

Manage sources:
```bash
heppyyier recipe list-sources    # show all registered sources
heppyyier recipe update          # git pull on all sources (refresh)
heppyyier recipe remove https://github.com/user/my-hep-recipes
```

Once added, packages from that source appear in `heppyyier avail` and can be installed
by name like any built-in:
```bash
heppyyier avail                  # shows built-in + remote recipes
heppyyier install mypackage      # finds recipe in remote source automatically
```

### One-off recipe file

To use a single recipe file without registering a source:

```bash
heppyyier install mypackage --recipe /path/to/mypackage/1.0.yaml
```

The `--recipe` flag accepts any absolute or relative path and overrides the built-in
and remote source search for that invocation.

### Recipe format

Recipes are YAML files named `<version>.yaml` inside a `<name>/` directory:

```
my-recipes/
  fastjet/
    3.5.1.yaml
  mycustomlib/
    2.0.yaml
```

See the built-in recipes under `src/heppyyier/recipes/` for the full format reference.

---

## Configuration reference

| Method | Key | Example |
|--------|-----|---------|
| Env var | `HEPPYYIER_PACKAGES_DIR` | `export HEPPYYIER_PACKAGES_DIR=/opt/hep` |
| `.heppyyier.toml` | `packages_dir` | `packages_dir = "/opt/hep"` |
| Default (venv) | — | `<venv>/heppyyier_packages/` |
| Default (no venv) | — | `./packages/` |

Legacy env var `HEPPYYIER_BUILD_DIR` and toml key `build_dir` are still accepted.
