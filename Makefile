# Cairn. `make validate` · `make build` · `make test`
#
# PY is discovered rather than assumed: Cairn needs Python >= 3.7 with PyYAML,
# and on an HPC login node the default `python3` often satisfies only one of
# those. Override with `make PY=/path/to/python` or export CAIRN_PYTHON.

PY ?= $(shell scripts/find_python.sh)

.PHONY: help setup init doctor install-commands validate build test clean python _python \
        digest standup sync push install-context site-check site-demo site-serve

# The graph is a separate repo now. Every data command reads it through
# CAIRN_ROOT, which the scripts resolve themselves — this variable exists so
# `make GRAPH=/path/to/graph validate` works without exporting anything.
# := not ?=, so CAIRN_ROOT is read once. A recursive `GRAPH ?= $(CAIRN_ROOT)`
# plus `export CAIRN_ROOT = $(GRAPH)` is a self-reference make refuses outright.
GRAPH := $(if $(GRAPH),$(GRAPH),$(CAIRN_ROOT))
ifneq ($(GRAPH),)
export CAIRN_ROOT := $(GRAPH)
endif

help:
	@echo "make setup             hook + commands + a path reminder (once per machine)"
	@echo "make init GRAPH=<path> create a research graph repo"
	@echo "make doctor            check this clone is set up, and say what is missing"
	@echo "make install-commands  make /log and /paper reachable from any repo"
	@echo "make validate          check every node against the schema"
	@echo "make build             regenerate build/graph.html and build/graph.md"
	@echo "make digest            what changed in the last 7 days, and what needs you"
	@echo "make standup           what to pick up today, most-needs-you first"
	@echo "make sync              pull the graph, and say what still needs you"
	@echo "make push              regenerate build/, commit it, and push"
	@echo "make test              run the test suite against the fixture graph"
	@echo "make python            show which interpreter Cairn will use"
	@echo ""
	@echo "make site-check       check every internal link in site/"
	@echo "make site-serve       preview site/ at http://localhost:8000"
	@echo "make site-demo ACK=1  regenerate the map demo embedded in site/"

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
	  echo "  Add these to your shell profile — the tool, then your graph:"; \
	  echo "    export CAIRN_PATH=$(CURDIR)"; \
	  echo "    export CAIRN_ROOT=$${CAIRN_ROOT:-/path/to/your-research-graph}"; }

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

# install_hooks needs a graph to install into, and on a fresh clone there may not
# be one yet — so it warns rather than failing the whole setup.
setup:
	@scripts/install_hooks.sh $(GRAPH) || \
	  echo "  (no graph yet — run: make init GRAPH=~/research-graph)"
	@$(MAKE) --no-print-directory _python
	@$(MAKE) --no-print-directory install-commands

init:
	@test -n "$(GRAPH)" || { \
	  echo "usage: make init GRAPH=~/research-graph" >&2; exit 2; }
	@bin/cairn init "$(GRAPH)" $(ARGS)

validate: _python
	@$(PY) scripts/validate.py

build: _python
	@$(PY) scripts/build_graph.py

digest: _python
	@$(PY) scripts/digest.py $(ARGS)

standup: _python
	@$(PY) scripts/standup.py $(ARGS)

# Deliberately not dependent on _python. sync's whole job is to work on a
# machine where something else is broken, so it goes through bin/cairn, which
# probes for an interpreter without demanding PyYAML for this command.
sync:
	@bin/cairn sync $(ARGS)

push:
	@bin/cairn sync --push $(ARGS)

install-context:
	@bin/cairn install_context $(ARGS)

test: _python
	@$(PY) tests/test_cairn.py

clean:
	@rm -f build/graph.html build/graph.md build/report.md

# ---------------------------------------------------------------------------
# The site (site/ -> GitHub Pages). Hand-written HTML, no generator.
# ---------------------------------------------------------------------------

site-check: _python
	@$(PY) scripts/check_site_links.py site

site-serve:
	@echo "cairn: serving site/ at http://localhost:8000  (ctrl-c to stop)"
	@cd site && $(PY) -m http.server 8000

# The demo embedded in site/map.html is a *publication* of the cairn subgraph:
# real node bodies, scrubbed but not thereby cleared. `export_example` refuses
# to write without --acknowledge-review, and this target refuses to pass that
# flag on your behalf — ACK=1 is you saying you read the review pass. Run it
# without ACK first; that prints the lines a human has to clear.
#
# CAIRN_EXAMPLE_EXCLUDE holds back nodes that must not be published at all.
CAIRN_EXAMPLE_EXCLUDE ?= 2026-08-21-cairn-hero-artifacts

site-demo: _python
	@test -n "$(ACK)" || { \
	  echo "cairn: this publishes real node bodies. Read the review pass first:" >&2; \
	  echo "" >&2; \
	  echo "    bin/cairn export_example --project cairn \\" >&2; \
	  echo "      $(foreach id,$(CAIRN_EXAMPLE_EXCLUDE),--exclude $(id)) " >&2; \
	  echo "" >&2; \
	  echo "  then re-run as: make site-demo ACK=1" >&2; \
	  exit 2; }
	@bin/cairn export_example --project cairn \
	  $(foreach id,$(CAIRN_EXAMPLE_EXCLUDE),--exclude $(id)) \
	  --dest example --acknowledge-review
	@CAIRN_ROOT=$(CURDIR)/example $(PY) scripts/build_graph.py >/dev/null
	@mkdir -p site/demo
	@cp example/build/graph.html site/demo/graph.html
	@echo "cairn: site/demo/graph.html regenerated ($$(wc -c < site/demo/graph.html) bytes)"
	@echo "  note: example/ and site/demo/ are gitignored pending the release review."
