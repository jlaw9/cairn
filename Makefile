PY ?= python3

.PHONY: help setup validate build test clean

help:
	@echo "make setup     install the pre-commit hook (once per clone)"
	@echo "make validate  check every node against the schema"
	@echo "make build     regenerate build/graph.html and build/graph.md"
	@echo "make test      run the test suite against the fixture graph"

setup:
	@scripts/install_hooks.sh
	@$(PY) -c "import yaml" 2>/dev/null || echo "warning: PyYAML missing — pip install pyyaml"

validate:
	@$(PY) scripts/validate.py

build:
	@$(PY) scripts/build_graph.py

test:
	@$(PY) tests/test_cairn.py

clean:
	@rm -f build/graph.html build/graph.md
