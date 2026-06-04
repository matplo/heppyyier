"""Auto-loaded via heppyyier_autoload.pth at Python startup.

Installs a lazy MetaPathFinder for every package whose HEPPYYIER_LOADED_*
env var is set (populated by 'module load <pkg>' via Lmod/Environment Modules).

The finder defers the actual heppyyier.load() call — which imports cppyy and
triggers its PCH build — to the moment user code first does `import <name>`.
This keeps Python startup instant even when modules are loaded, which matters
on HPC systems where the cppyy PCH build on a network filesystem can hang.
"""
import os as _os
import sys as _sys

if any(k.startswith("HEPPYYIER_LOADED_") for k in _os.environ):
    try:
        import importlib.abc as _abc
        import importlib.machinery as _machinery
        import heppyyier as _h
        from heppyyier.registry import get_registry as _gr

        _names = [n for n in _gr().all_packages()
                  if _os.environ.get("HEPPYYIER_LOADED_" + n.upper().replace("-", "_"))]
        # ROOT must go first so its lib/ lands in sys.path before any
        # `import cppyy` — that way ROOT's bundled cppyy wins over pip-cppyy.
        if "root" in _names:
            _names.remove("root")
            _names.insert(0, "root")

        _pending = list(_names)

        class _HeppyyierLazyLoader(_abc.Loader):
            def __init__(self, mod):
                self._mod = mod

            def create_module(self, spec):
                return self._mod  # reuse the proxy _h.load() already placed in sys.modules

            def exec_module(self, module):
                pass  # nothing to execute; module is already fully set up

        class _HeppyyierFinder(_abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname not in _pending or fullname in _sys.modules:
                    return None
                # One-shot: load all pending packages in order, then uninstall.
                to_load = list(_pending)
                _pending.clear()
                _sys.meta_path[:] = [f for f in _sys.meta_path
                                     if not isinstance(f, _HeppyyierFinder)]
                for _name in to_load:
                    try:
                        _h.load(_name)
                    except Exception as _e:
                        print(f"[heppyyier] lazy load failed for {_name!r}: {_e}",
                              file=_sys.stderr)
                if fullname in _sys.modules:
                    return _machinery.ModuleSpec(
                        fullname,
                        _HeppyyierLazyLoader(_sys.modules[fullname]),
                        origin="heppyyier",
                    )
                return None

        _sys.meta_path.insert(0, _HeppyyierFinder())

    except Exception:
        pass
