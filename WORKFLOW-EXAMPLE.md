# heppyyier — workflow examples

Quick-reference for the most common setups. Jump to the section that matches your situation.

---

## Prerequisites

### heppyyier

Install into any Python virtual environment:

```bash
pip install git+https://github.com/matplo/heppyyier.git
```

### henv (recommended)

[henv](https://github.com/matplo/henv) is a single-script virtual environment manager
designed for heppyyier workflows. It creates and activates venvs, installs heppyyier
on first use, wires up tab completion, regenerates modulefiles, and handles
`HEPPYYIER_PACKAGES_DIR` / `HEPPYYIER_SYSTEM_PACKAGES_DIR` automatically.

Install once (requires `curl`):

```bash
curl -fsSL https://raw.githubusercontent.com/matplo/henv/main/henv | bash -s -- --install
```

This places `henv` in `~/.local/bin/`. Make sure that directory is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"   # add to ~/.bashrc or ~/.zshrc
```

Verify:
```bash
henv --version
```

henv is optional — all heppyyier commands work in any plain venv. The workflows below
use `henv .` for convenience, but any `henv` call can be replaced with:

```bash
python -m venv .venv && source .venv/bin/activate
pip install git+https://github.com/matplo/heppyyier.git
heyy init
```

---

## 1. Local development (macOS / Linux laptop)

The default setup — packages live inside your venv, nothing shared.

```bash
# One-time: create a venv and install heppyyier
pip install henv        # or: curl … ~/.local/bin/henv
henv .                  # create .venv in current dir, install heppyyier, drop in

# Build packages (inside the henv subshell):
heyy install fastjet hepmc3 lhapdf pythia8 fjcontrib

# Use in Python:
python my_analysis.py   # if you used 'module load' in the subshell
# or explicitly:
python -c "
import heppyyier
heppyyier.load('fastjet')
heppyyier.load('pythia8')
import fastjet, pythia8
print(fastjet.PseudoJet(1,0,1,1.4).pt())
"

exit                    # leave the henv subshell
```

Re-entering later (no rebuild):
```bash
henv .                  # existing env — activates immediately, no prompts
```

---

## 2. Google Colab (ephemeral runtime + Google Drive cache)

Colab runtimes reset on disconnect. Mount Google Drive once and store compiled
packages there so only `pip install heppyyier` (seconds) is needed each session.

```python
# ── Cell 1: always run ─────────────────────────────────────────────────────
!pip install git+https://github.com/matplo/heppyyier.git -q

from google.colab import drive
drive.mount('/content/drive')

import os
# Point heppyyier at a persistent Drive directory
os.environ["HEPPYYIER_PACKAGES_DIR"] = "/content/drive/MyDrive/hep_packages"

# ── Cell 2: build once, then skip this cell in future sessions ─────────────
# !heyy init
# !heyy install fastjet hepmc3 lhapdf pythia8 fjcontrib --verbose

# ── Cell 3: every session ──────────────────────────────────────────────────
import heppyyier
heppyyier.load("fastjet")
heppyyier.load("pythia8")
import fastjet, pythia8
print("fastjet", fastjet.__version__ if hasattr(fastjet, '__version__') else "ok")
```

> **Compatibility note:** compiled packages (ELF binaries) are platform-specific.
> Colab-built packages work on Colab; NERSC-built packages work on NERSC.
> Do not mix across incompatible systems.

---

## 3. HPC — single user (NERSC, Perlmutter, etc.)

Packages in your own directory; no sharing, no special flags.

```bash
# Set a persistent location (add to ~/.bashrc):
export HEPPYYIER_PACKAGES_DIR=$HOME/.heppyyier_packages

# Create and enter a venv (henv auto-detects HEPPYYIER_PACKAGES_DIR):
henv .

# Build packages (first time; cppyy may take 30-90 min on NERSC):
heyy recipe update
heyy install fastjet hepmc3 lhapdf pythia8 fjcontrib
heyy install cppyy --force        # builds cling from source with system g++ (GCC 13)

# Generate Lmod/TCL modulefiles:
heyy generate-modules
# henv already ran 'eval "$(heyy modules)"' on subshell entry — module load works immediately

# Load and use:
module load fastjet pythia8
python analysis.py
```

> **NERSC / SUSE Linux note:** the binary pip-cppyy wheel is incompatible with
> SUSE GCC headers. `heyy install cppyy --force` builds cling from source with
> the system `g++` (GCC 13) and resolves the issue permanently.

---

## 4. HPC — admin builds, users share (read-only shared filesystem)

An admin builds the packages once; all users on the system can load them
without any compilation.

### Admin (once):
```bash
export HEPPYYIER_PACKAGES_DIR=/global/cfs/cdirs/myproject/hep_packages
henv --packages-dir $HEPPYYIER_PACKAGES_DIR .
heyy install fastjet hepmc3 lhapdf pythia8 fjcontrib
heyy install cppyy --force       # source build with system GCC
heyy generate-modules            # write modulefiles into the same tree
```

### Each user (no compilation):
```bash
export HEPPYYIER_PACKAGES_DIR=/global/cfs/cdirs/myproject/hep_packages
heyy kernel install              # personal kernel.json pointing at shared packages

# With henv — module use is registered automatically on subshell entry:
henv --packages-dir /global/cfs/cdirs/myproject/hep_packages .
module load fastjet pythia8
python analysis.py

# Without henv (plain venv activation) — register modulefiles dir manually:
source .venv/bin/activate
eval "$(heyy modules)"
module load fastjet pythia8
python analysis.py
```

---

## 5. HPC — two-tier: shared base + personal installs

Admin provides a read-only base; users can install additional packages to
their own directory without affecting anyone else.

### Admin (once):
```bash
export HEPPYYIER_PACKAGES_DIR=/shared/hep/packages
heyy install fastjet hepmc3 lhapdf pythia8 fjcontrib cppyy --force
heyy generate-modules
```

### User B:
```bash
# My own writable dir (default: inside venv)
# Shared read-only base from admin
export HEPPYYIER_SYSTEM_PACKAGES_DIR=/shared/hep/packages

henv --system-packages-dir /shared/hep/packages .
# Inside the subshell:
#   HEPPYYIER_PACKAGES_DIR  = .venv/heppyyier_packages/  (writable, user-local)
#   HEPPYYIER_SYSTEM_PACKAGES_DIR = /shared/hep/packages  (read-only)

heyy list               # shows shared packages as if they were locally installed
heyy install myprivatelib   # goes to .venv/heppyyier_packages/ only
python -c "import heppyyier; heppyyier.load('fastjet')"  # resolves from shared
```

Or configure permanently in `.heppyyier.toml` at the project root:
```toml
# .heppyyier.toml
system_packages_dir = "/shared/hep/packages"
```
`henv .` will then pick this up automatically on every activation.

---

## 6. Jupyter / JupyterHub

Register a kernel so notebooks can use all installed packages without any
`module load` in the terminal first.

```bash
pip install ipykernel
heyy kernel install                     # default name: heppyyier-<venv>
heyy kernel install --display-name "HEP 2026"   # custom label in JupyterHub UI
heyy kernel install --sys-prefix        # install for all users on a JupyterHub
```

The kernel spec embeds `PATH`, `LD_LIBRARY_PATH`, `PYTHONPATH`, and
`HEPPYYIER_PACKAGES_DIR` for every installed package. In a notebook cell:

```python
import heppyyier
heppyyier.load("fastjet")
heppyyier.load("pythia8")
import fastjet, pythia8, cppyy
jet = fastjet.PseudoJet(1.0, 0.0, 1.0, 1.414)
print(jet.pt())
```

After installing new packages, refresh the kernel spec:
```bash
heyy kernel install          # same --name replaces the existing spec in place
```

For a shared JupyterHub pointing at the admin-built packages (workflow 4/5):
```bash
export HEPPYYIER_PACKAGES_DIR=/shared/hep/packages
heyy kernel install --display-name "HEP shared" --sys-prefix
```

---

## 7. ROOT sessions

ROOT builds its own cling — preferred on HPC systems where pip-cppyy is
incompatible with the system GCC.

```bash
heyy recipe update
heyy install root           # ~30 min; builds ROOT with system compiler
```

```python
import heppyyier
heppyyier.load("root")      # ROOT's cling is now the active interpreter
heppyyier.load("fastjet")   # uses ROOT's cling — no pip-cppyy conflict
heppyyier.load("pythia8")
import ROOT, fastjet, pythia8
```

With `module load` the autoload hook loads ROOT first automatically:
```bash
module load root fastjet pythia8
python analysis.py          # all packages share ROOT's cling
```

---

## 8. Using packages registered from another build system

If packages were built by [yasp](https://github.com/matplo/yasp) or any other
tool, register the existing prefix without rebuilding:

```bash
heyy register fastjet --prefix /path/to/fastjet/3.5.1 --version 3.5.1
heyy register pythia8 --prefix /path/to/pythia8/8.317  --version 8.317
heyy kernel install
```

---

## Quick reference

| Goal | Command |
|------|---------|
| Create local venv + heppyyier | `henv .` |
| Build all core packages | `heyy install fastjet hepmc3 lhapdf pythia8 fjcontrib` |
| Build cppyy from source (HPC) | `heyy install cppyy --force` |
| Share packages (admin) | `export HEPPYYIER_PACKAGES_DIR=/shared/…; heyy install …` |
| Use shared packages (user) | `export HEPPYYIER_PACKAGES_DIR=/shared/…` |
| Add personal packages on top of shared | `henv --system-packages-dir /shared/… .` |
| Register Jupyter kernel | `heyy kernel install` |
| Refresh modulefiles | `heyy generate-modules` |
| Update heppyyier + recipes | `heyy upgrade && heyy recipe update` |
