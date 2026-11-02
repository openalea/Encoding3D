# Contributing

fspm-TF is a format shared by several FSPM platforms. Contributions are welcome from each of them: to the
specification, to the vocabulary, to a codec, to the tools.

## What goes where

- **`spec/`**: the agreement between the platforms (the specification, its JSON Schemas, the vocabulary). A change
  there is proposed as a pull request, with the conformance scene showing it (`conformance/generate.py` and the
  files it writes), the validator's check and the reference codec's update. See
  [Changing the format](doc/governance.md).
- **The vocabulary** (`spec/vocabulary/`): a new standard name comes with its definition, canonical unit and kind,
  and is agreed by at least two platforms. Each platform fills its own column of names.
- **`bindings/<language>/`**: one codec per language, each with its own build, tests and release, maintained by its
  team. A codec passes the conformance check (`conformance/README.md`) in its CI.
- **Adapters** (a platform's model to and from the tables) stay in the platforms' own repositories.

## Developing the Python package

```bash
mamba env create -f conda/environment.yml        # the package, editable, with the tests' and the docs' tools
mamba activate fspm_tf
pytest                                           # the package's tests (bindings/python/test)
pytest --nbmake doc/notebooks                    # the documentation's notebooks run
python -m sphinx -b html doc doc/_build -W       # the documentation, warnings as errors
python conformance/generate.py                   # after a change to the conformance scenes
```

Commit with explicit messages, one subject per commit, and open the pull request on the development branch.
