"""Auto-loaded via heppyyier_autoload.pth at Python startup.

Calls heppyyier.load() for every package whose HEPPYYIER_LOADED_* env var is
set (populated by 'module load <pkg>' when using Lmod/Environment Modules).
"""
import os as _os

if any(k.startswith("HEPPYYIER_LOADED_") for k in _os.environ):
    try:
        import heppyyier as _h
        from heppyyier.registry import get_registry as _gr
        for _name in _gr().all_packages():
            _key = "HEPPYYIER_LOADED_" + _name.upper().replace("-", "_")
            if _os.environ.get(_key):
                try:
                    _h.load(_name)
                except Exception as _e:
                    import sys as _sys
                    print(f"[heppyyier] autoload failed for {_name!r}: {_e}",
                          file=_sys.stderr)
    except Exception:
        pass
