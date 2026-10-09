from __future__ import annotations

import importlib
import json
import platform
import sys

MODULES = (
    "panel",
    "holoviews",
    "hvplot",
    "datashader",
    "duckdb",
    "dynamical_catalog",
    "bokeh",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "xarray",
    "colorcet",
    "resvg_py",
)


def main() -> int:
    result: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "modules": {},
    }
    failed = False
    for name in MODULES:
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            result["modules"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            failed = True
        else:
            result["modules"][name] = {
                "ok": True,
                "version": getattr(module, "__version__", "unknown"),
            }
    print(json.dumps(result, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
