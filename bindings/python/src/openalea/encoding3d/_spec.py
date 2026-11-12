"""
Where the specification's files are: the spec/ folder of the encoding3d repository, shipped with the installed package as
openalea.encoding3d.spec (pyproject's package-dir), or found in a clone from bindings/python/src (e.g. ParaView's plugin,
which puts only that folder on its path).
"""
import os


def path(*parts: str) -> str:
    """The path of a file of the specification, e.g. path("schema", "index.schema.json")."""
    try:
        from openalea.encoding3d import spec
        base = list(spec.__path__)[0]
    except ImportError:
        here = os.path.dirname(os.path.abspath(__file__))                 # bindings/python/src/openalea/encoding3d
        base = os.path.join(here, os.pardir, os.pardir, os.pardir, os.pardir, os.pardir, "spec")
    return os.path.join(os.path.normpath(base), *parts)
