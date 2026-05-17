"""Auto-discovery: importing this package imports every tool module,
which fires the `@app.tool()` decorators and populates the FastMCP registry.
Drop a new file in this directory and it's live.
"""

from __future__ import annotations

import importlib
import pkgutil


for _m in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_m.name}")
