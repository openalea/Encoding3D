# -*- coding: utf-8 -*-
"""Sphinx configuration of encoding3d's documentation. The vocabulary's pages are generated from spec/vocabulary at each
build (_generated/), so that they never differ from the agreed files."""
import csv
import json
import os
import sys
from importlib.metadata import metadata

import pydata_sphinx_theme  # noqa: F401  (Pydata theme: https://pydata-sphinx-theme.readthedocs.io/en/stable/index.html)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The package's metadata (pyproject.toml), as every OpenAlea documentation reads it
package = "openalea.encoding3d"
meta = metadata(package)
project = "encoding3d"
release = meta.get("version")
version = ".".join(release.split(".")[:3])
author = meta["Author-email"].split(" <")[0]
desc = meta["Summary"]
urls = {key.strip(): value.strip() for key, value in (item.split(",") for item in meta.get_all("Project-URL"))}

# The package's root, for autodoc when it is not installed (its sources are in bindings/python/src)
sys.path.insert(0, os.path.join(ROOT, "bindings", "python", "src"))

# -- General configuration ------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",       # support for automatic inclusion of docstrings
    "sphinx.ext.autosummary",   # generates autodoc summaries
    "sphinx.ext.doctest",       # inclusion and testing of doctest code snippets
    "sphinx.ext.intersphinx",   # support for linking to other projects
    "sphinx.ext.mathjax",       # support for math equations
    "sphinx.ext.ifconfig",      # support for conditional content
    "sphinx.ext.viewcode",      # support for links to source code
    "sphinx.ext.coverage",      # includes doc coverage stats in the documentation
    "sphinx.ext.todo",          # support for todo items
    "sphinx.ext.napoleon",      # support for numpy and google style docstrings
    "sphinx_favicon",           # support for favicon
    "sphinx_copybutton",        # support for copybutton in code blocks
    "nbsphinx",                 # for integrating jupyter notebooks
    "myst_parser",              # for parsing .md files
]
templates_path = ["_templates"]
autosummary_generate = True
exclude_patterns = ["build", "_build", "_templates", "**.ipynb_checkpoints"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
master_doc = "index"
copyright = "Cecill-C INRAE / INRIA / CIRAD"
language = "en"
pygments_style = "sphinx"
todo_include_todos = False
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3
autodoc_member_order = "bysource"
nbsphinx_execute = "always"     # the notebooks run at each build, as nbmake runs them in the tests

# -- Options for HTML output ----------------------------------------------
html_theme = "pydata_sphinx_theme"
html_theme_options = {
    "header_links_before_dropdown": 6,
    "icon_links": [{"name": "GitHub", "url": urls["Repository"], "icon": "fa-brands fa-github"}],
    "show_version_warning_banner": True,
    "footer_start": ["copyright"],
    "footer_center": ["sphinx-version"],
    "secondary_sidebar_items": {"**/*": ["page-toc", "edit-this-page", "sourcelink"], "examples/no-sidebar": []},
    "use_edit_page_button": True,
}
html_static_path = ["_static"]
html_logo = "_static/openalea_web.svg"
html_favicon = "_static/openalea_web.svg"
html_domain_indices = True
html_use_index = True
html_split_index = False
html_show_sourcelink = True
html_show_sphinx = True
html_show_copyright = True
htmlhelp_basename = "encoding3d_documentation"
html_context = {"github_user": "openalea", "github_repo": "encoding3d", "github_version": "main", "doc_path": "doc"}

# -- Options for LaTeX, manual page and Texinfo output ---------------------
latex_elements = {}
latex_documents = [(master_doc, "encoding3d.tex", "encoding3d Documentation", "INRAE / inria / CIRAD", "manual")]
man_pages = [(master_doc, "encoding3d", "encoding3d Documentation", [author], 1)]
texinfo_documents = [(master_doc, "encoding3d", "encoding3d Documentation", author, "encoding3d", desc, "Miscellaneous")]
intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}


# ── The vocabulary's pages, from spec/vocabulary ───────────────────────────

def _escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _table(header: list, rows: list) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_escape(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def write_vocabulary_pages(app=None) -> None:
    folder = os.path.join(HERE, "_generated")
    os.makedirs(folder, exist_ok=True)
    vocabulary = os.path.join(ROOT, "spec", "vocabulary")
    with open(os.path.join(vocabulary, "standard_names.csv"), encoding="utf-8", newline="") as file:
        names = list(csv.DictReader(file))
    with open(os.path.join(vocabulary, "labels.csv"), encoding="utf-8", newline="") as file:
        labels = list(csv.DictReader(file))
    with open(os.path.join(vocabulary, "enums.json"), encoding="utf-8") as file:
        enums = json.load(file)
    platforms = ("metafspm", "cplantbox", "groimp", "virtualplantlab")
    pages = {
        "standard_names.md": _table(
            ["standard name", "unit", "kind", "definition", "typical scales"],
            [[f"`{row['standard_name']}`", f"`{row['canonical_unit']}`", row["kind"], row["definition"],
              row["typical_scales"]] for row in names]),
        "decomposition.md": _table(
            ["standard name", "property", "object of interest", "matrix", "context"],
            [[f"`{row['standard_name']}`", row["property"], row["object_of_interest"], row["matrix"], row["context"]]
             for row in names]),
        "platform_names.md": _table(
            ["standard name"] + list(platforms) + ["notes"],
            [[f"`{row['standard_name']}`"] + [", ".join(f"`{n.strip()}`" for n in (row[p] or "").split(";") if n.strip())
                                               for p in platforms] + [row["notes"]] for row in names]),
        "labels.md": _table(
            ["label", "scale", "Plant Ontology", "note"],
            [[f"`{row['label']}`", row["scale"],
              f"[{row['plant_ontology']}](http://purl.obolibrary.org/obo/{row['plant_ontology'].replace(':', '_')}) "
              f"{row['plant_ontology_label']}" if row["plant_ontology"] else "", row["note"]] for row in labels]),
        "enums.md": "\n".join(
            f"**{name}**\n\n" + _table(["value", "meaning"], [[f"`{key}`", meaning] for key, meaning in values.items()])
            for name, values in enums.items() if isinstance(values, dict))
            + "\n**scales** (base scales, coarser first): " + ", ".join(f"`{s}`" for s in enums["scales"]) + "\n",
    }
    for name, text in pages.items():
        path = os.path.join(folder, name)
        if not os.path.exists(path) or open(path, encoding="utf-8").read() != text:
            with open(path, "w", encoding="utf-8") as file:
                file.write(text)


def setup(app):
    app.connect("builder-inited", write_vocabulary_pages)
