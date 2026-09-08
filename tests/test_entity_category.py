"""Everything that writes the settings block must be Configuration.

Home Assistant's device page has exactly four groups — Controls, Sensors,
Configuration and Diagnostic — and an entity lands in one purely by its
``EntityCategory``. Before this, nothing declared ``CONFIG``, so the page showed
three groups and all fourteen settings-block entities piled into Controls
alongside the light and fan.

These modules import Home Assistant, so they are read as source rather than
imported. That is weaker than exercising the real entities, but it does catch
the regression that actually happened: a description quietly carrying
``entity_category=None``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from conftest import COMPONENT

SETTINGS_PLATFORMS = ("number.py", "select.py")


def module(name: str) -> ast.Module:
    return ast.parse((Path(COMPONENT) / name).read_text())


def keyword_values(tree: ast.Module, name: str) -> list[ast.expr]:
    """Every ``name=...`` keyword argument anywhere in the module."""
    return [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == name
    ]


def is_config(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "CONFIG"
        and isinstance(node.value, ast.Name)
        and node.value.id == "EntityCategory"
    )


@pytest.mark.parametrize("name", SETTINGS_PLATFORMS)
def test_platform_declares_the_config_category(name: str) -> None:
    """The category has to appear somewhere, as a default or per entity."""
    source = (Path(COMPONENT) / name).read_text()
    assert "EntityCategory.CONFIG" in source


@pytest.mark.parametrize("name", SETTINGS_PLATFORMS)
def test_no_entity_opts_back_out_to_none(name: str) -> None:
    """Regression: ``number.py`` set ``entity_category=None`` on the fan presets.

    An explicit None overrides the table's default and drops that entity back
    into Controls, which is exactly the bug this guards against — and it is
    invisible, because the entity still works perfectly.
    """
    for value in keyword_values(module(name), "entity_category"):
        assert not (
            isinstance(value, ast.Constant) and value.value is None
        ), f"{name} sets entity_category=None, which puts a setting back in Controls"


def test_number_descriptions_default_to_config() -> None:
    """The default lives on the description class, not on fourteen entries."""
    tree = module("number.py")
    defaults = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "entity_category"
        and node.value is not None
    ]
    assert defaults, "SaferaNumberDescription should default entity_category"
    assert all(is_config(default) for default in defaults)


def test_operable_entities_stay_in_controls() -> None:
    """The things you actually operate must not drift into Configuration.

    The light, the fan, the two auto switches and the filter reset are the
    device page's Controls group. If these ever pick up a category the group
    empties out and the device looks inert.
    """
    for name in ("light.py", "fan.py", "switch.py", "button.py"):
        source = (Path(COMPONENT) / name).read_text()
        assert "EntityCategory" not in source, (
            f"{name} is an operable entity and should stay uncategorised"
        )
