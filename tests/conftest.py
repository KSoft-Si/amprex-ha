"""Load the HA-free modules directly, without importing Home Assistant."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PACKAGE = Path(__file__).parents[1] / "custom_components" / "amprex"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"amprex_{name}", _PACKAGE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def pairing():
    return _load("pairing")


@pytest.fixture(scope="session")
def protocol():
    return _load("protocol")
