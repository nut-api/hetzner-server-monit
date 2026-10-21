"""Per-channel focus lists + last-seen availability, persisted as one JSON file."""

import json
import os
from pathlib import Path
from typing import NamedTuple

from hetzner import Product


class Change(NamedTuple):
    model: str
    channel_id: int
    available: bool | None  # None: unknown
    was: bool | None
    product: Product | None  # None when the model is missing from the page


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        focus = data.get("focus", {})
        if focus and isinstance(next(iter(focus.values())), int):
            # Old format: one server-wide list, model -> channel id.
            migrated: dict[str, list[str]] = {}
            for model, channel_id in focus.items():
                migrated.setdefault(str(channel_id), []).append(model)
            focus = migrated
        self.focus: dict[str, list[str]] = focus  # channel id -> models
        self.last: dict[str, bool | None] = data.get("last", {})  # model -> available (None: unknown)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"focus": self.focus, "last": self.last}, indent=2))
        os.replace(tmp, self.path)

    def watched(self, channel_id: int) -> list[str]:
        return sorted(self.focus.get(str(channel_id), []))

    def add(self, channel_id: int, model: str, available: bool | None) -> None:
        models = self.focus.setdefault(str(channel_id), [])
        if model not in models:
            models.append(model)
        self.last[model] = available
        self.save()

    def remove(self, channel_id: int, model: str) -> bool:
        models = self.focus.get(str(channel_id), [])
        if model not in models:
            return False
        models.remove(model)
        if not models:
            del self.focus[str(channel_id)]
        if not any(model in m for m in self.focus.values()):
            self.last.pop(model, None)
        self.save()
        return True

    def apply(self, products: dict[str, Product]) -> list[Change]:
        """Record a fresh scrape; return one change per channel watching a model whose state changed.

        A watched model missing from `products` is unknown, so `apply({})` marks everything unknown.
        """
        flipped: dict[str, tuple[bool | None, bool | None]] = {}
        for model in {m for models in self.focus.values() for m in models}:
            product = products.get(model)
            now = product.available if product else None
            if model in self.last and self.last[model] != now:
                flipped[model] = (now, self.last[model])
            self.last[model] = now
        self.save()
        return [
            Change(model, int(channel_id), *flipped[model], products.get(model))
            for channel_id, models in self.focus.items()
            for model in models
            if model in flipped
        ]
