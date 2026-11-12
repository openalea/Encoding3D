"""The JSON Schemas of encoding3d (spec/schema/): fspm_scene.schema.json (the FSPM_scene extension),
index.schema.json (a sequence's scene.fspm.json), views.schema.json (a sequence's views.json) and coupling.schema.json
(a coupling session's messages)."""
import json
from functools import lru_cache

from openalea.encoding3d import _spec


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    with open(_spec.path("schema", f"{name}.schema.json"), encoding="utf-8") as file:
        return json.load(file)
