# Cairn. `make validate` · `make build` · `make test`
#
# PY is discovered rather than assumed: Cairn needs Python >= 3.7 with PyYAML,
# and on an HPC login node the default `python3` often satisfies only one of
# those. Override with `make PY=/path/to/python` or export CAIRN_PYTHON.

PY ?= $(shell scripts/find_python.sh)

.PHONY: help setup doctor install-commands validate build test clean python _python

help:
	@echo "make setup             hook + commands + a CAIRN_PATH reminder (once per machine)"
	@echo "make doctor            check this clone is set up, and say what is missing"
	@echo "make install-commands  make /log and /paper reachable from any repo"
	@echo "make validate          check every node against the schema"
	@echo "make build             regenerate build/graph.html and build/graph.md"
	@echo "make test              run the test suite against the fixture graph"
	@echo "make python            show which interpreter Cairn will use"

# Deliberately not dependent on _python: the most common thing to be wrong is
# the Python, and a check that can't run on a broken install is no use.
doctor:
	@scripts/doctor.sh

# Slash commands resolve from the *session's* project directory plus
# ~/.claude/commands. Cairn's live in this repo, so without this they are
# reachable only from a session rooted here — while /log's whole job is to run
# from inside a project repo. Symlink rather than copy so edits here take
# effect everywhere immediately.
install-commands:
	@mkdir -p "$(HOME)/.claude/commands"
	@for f in $(CURDIR)/.claude/commands/*.md; do \
	  ln -sf "$$f" "$(HOME)/.claude/commands/$$(basename $$f)"; \
	  echo "  /$$(basename $$f .md) -> $$f"; \
	done
	@echo "cairn: commands installed for this machine"
	@grep -qs "CAIRN_PATH" "$(HOME)/.bashrc" "$(HOME)/.zshrc" || { \
	  echo ""; \
	  echo "  Add this to your shell profile so the commands can find the graph:"; \
	  echo "    export CAIRN_PATH=$(CURDIR)"; }

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
	@$(MAKE) --no-print-directory install-commands

validate: _python
	@$(PY) scripts/validate.py

build: _python
	@$(PY) scripts/build_graph.py

test: _python
	@$(PY) tests/test_cairn.py

clean:
	@rm -f build/graph.html build/graph.md
