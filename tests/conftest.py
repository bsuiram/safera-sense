"""Make the pure parts of the integration importable without Home Assistant.

``parser.py`` and ``const.py`` are deliberately free of Home Assistant and bleak
imports, so they can be loaded directly. Importing the real package would
execute ``__init__.py``, which does need Home Assistant, so they are loaded
under a synthetic package instead. The package is what makes ``parser.py``'s
``from .const import ...`` resolve.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "safera"

PACKAGE = "safera_pure"


def _package() -> ModuleType:
    if PACKAGE in sys.modules:
        return sys.modules[PACKAGE]
    pkg = ModuleType(PACKAGE)
    pkg.__path__ = [str(COMPONENT)]
    sys.modules[PACKAGE] = pkg
    return pkg


def _load(name: str) -> ModuleType:
    _package()
    qualified = f"{PACKAGE}.{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(qualified, COMPONENT / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


const = _load("const")
parser = _load("parser")
