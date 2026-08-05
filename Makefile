# Cairn. `make validate` · `make build` · `make test`
#
# PY is discovered rather than assumed: Cairn needs Python >= 3.7 with PyYAML,
# and on an HPC login node the default `python3` often satisfies only one of
# those. Override with `make PY=/path/to/python` or export CAIRN_PYTHON.

PY ?= $(shell scripts/find_python.sh)

.PHONY: help setup validate build test clean python _python

help:
	@echo "make setup     install the pre-commit hook (once per clone)"
	@echo "make validate  check every node against the schema"
	@echo "make build     regenerate build/graph.html and build/graph.md"
	@echo "make test      run the test suite against the fixture graph"
	@echo "make python    show which interpreter Cairn will use"

# Fail with something actionable instead of a SyntaxError from a Python too old
# to parse lib.py.
_python:
	@test -n "$(PY)" || { \
	  echo "cairn: no usable Python found (need >= 3.7 with PyYAML)." >&2; \
	  echo "  Cairn only needs PyYAML — 'pip install --user pyyaml' on any" >&2; \
	  echo "  python3.7+ is enough, or point at one you already have:" >&2; \
	  echo "    export CAIRN_PYTHON=/path/to/python" >&2; \
	  exit 1; }

python: _python
	@echo "$(PY)"

setup:
	@scripts/install_hooks.sh
	@$(MAKE) --no-print-directory _python

validate: _python
	@$(PY) scripts/validate.py

build: _python
	@$(PY) scripts/build_graph.py

test: _python
	@$(PY) tests/test_cairn.py

clean:
	@rm -f build/graph.html build/graph.md
