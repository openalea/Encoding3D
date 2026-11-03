"""The JSON Schemas of fspm-TF (spec/schema/): fspm_scene.schema.json (the FSPM_scene extension),
index.schema.json (a sequence's scene.fspm.json) and coupling.schema.json (a coupling session's messages)."""
import json
from functools import lru_cache

from openalea.fspm_tf import _spec


@lru_cache(maxsize=None)
def load(name: str) -> dict:
    with open(_spec.path("schema", f"{name}.schema.json"), encoding="utf-8") as file:
        return json.load(file)
