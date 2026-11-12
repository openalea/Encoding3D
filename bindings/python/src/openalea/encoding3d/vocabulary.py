"""
The encoding3d vocabulary (spec/vocabulary/)::

    standard_names.csv    the standard names: canonical unit (UCUM), kind, I-ADOPT decomposition, scales, definition,
                          and the names each platform gives the quantity (one column per platform)
    labels.csv            entity labels with their scale and Plant Ontology term
    enums.json            the values of edge_type, kind, role, data structure and grid kinds; the base scales

    platform_names("metafspm")      {a metafspm name: its standard name}, from the metafspm column
"""
import csv
import json
from functools import lru_cache

from openalea.encoding3d import _spec

PLATFORMS = ("metafspm", "cplantbox", "groimp", "virtualplantlab")     # the platform columns of standard_names.csv


def path(name: str) -> str:
    return _spec.path("vocabulary", name)


@lru_cache(maxsize=None)
def standard_names() -> dict:
    """{standard name: its row (canonical_unit, kind, property, object_of_interest, ..., one column per platform)}."""
    with open(path("standard_names.csv"), encoding="utf-8", newline="") as file:
        return {row["standard_name"]: row for row in csv.DictReader(file)}


@lru_cache(maxsize=None)
def platform_names(platform: str) -> dict:
    """{name on *platform*: standard name}: the platform's column, names separated by ';'."""
    if platform not in PLATFORMS:
        raise ValueError(f"no column for '{platform}' in the vocabulary (platforms: {PLATFORMS})")
    found = {}
    for standard_name, row in standard_names().items():
        for name in (row.get(platform) or "").split(";"):
            if name.strip():
                found[name.strip()] = standard_name
    return found


@lru_cache(maxsize=None)
def labels() -> dict:
    """{label: its row (scale, plant_ontology, plant_ontology_label, note)}."""
    with open(path("labels.csv"), encoding="utf-8", newline="") as file:
        return {row["label"]: row for row in csv.DictReader(file)}


@lru_cache(maxsize=None)
def enums() -> dict:
    with open(path("enums.json"), encoding="utf-8") as file:
        return json.load(file)


def version() -> str:
    return enums()["version"]
