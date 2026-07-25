"""Layer-state helpers shared by geometry, semantics, and rendering."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic
from ezdxf.layouts import BaseLayout


def hidden_layers(doc: Drawing) -> set[str]:
    return {
        layer.dxf.name.casefold()
        for layer in doc.layers
        if (not layer.is_on()) or layer.is_frozen()
    }


def iter_entities(
    layout: BaseLayout,
    doc: Drawing,
    *,
    respect_layer_state: bool = True,
) -> Iterator[DXFGraphic]:
    hidden = hidden_layers(doc) if respect_layer_state else set()
    for entity in layout:
        layer = str(entity.dxf.get("layer", "0")).casefold()
        if layer not in hidden:
            yield entity


def all_layer_names(doc: Drawing, layouts: Iterable[BaseLayout] | None = None) -> dict[str, bool]:
    names = {layer.dxf.name: True for layer in doc.layers}
    source = layouts if layouts is not None else doc.layouts
    for layout in source:
        for entity in layout:
            names.setdefault(str(entity.dxf.get("layer", "0")), False)
    return names


def layer_state(layer: Any) -> dict[str, Any]:
    return {
        "name": layer.dxf.name,
        "on": layer.is_on(),
        "frozen": layer.is_frozen(),
        "locked": layer.is_locked(),
        "color": layer.color,
        "linetype": layer.dxf.linetype,
        "lineweight": layer.dxf.lineweight,
        "transparency": layer.transparency,
    }
