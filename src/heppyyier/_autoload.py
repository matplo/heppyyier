"""Auto-loaded via heppyyier_autoload.pth at Python startup.

Calls heppyyier.load() for every package whose HEPPYYIER_LOADED_* env var is
set (populated by 'module load <pkg>' when using Lmod/Environment Modules).
"""
import os as _os

if any(k.startswith("HEPPYYIER_LOADED_") for k in _os.environ):
    try:
        import heppyyier as _h
        from heppyyier.registry import get_registry as _gr
        _names = [n for n in _gr().all_packages()
                  if _os.environ.get("HEPPYYIER_LOADED_" + n.upper().replace("-", "_"))]
        # ROOT must load first so its lib/ lands in sys.path before any
        # `import cppyy` — that way ROOT's bundled cppyy wins over pip-cppyy
        # and all subsequent packages share ROOT's cling.
        if "root" in _names:
            _names.remove("root")
            _names.insert(0, "root")
        for _name in _names:
            try:
                _h.load(_name)
            except Exception as _e:
                import sys as _sys
                print(f"[heppyyier] autoload failed for {_name!r}: {_e}",
                      file=_sys.stderr)
    except Exception:
        pass
