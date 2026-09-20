# webgrab -- the same target vocabulary every consumer gets, so it transfers.
#
#   make test          offline suite; never touches the network
#   make test-network  opt-in live checks
#   make probe         re-verify every working source in the registry
#   make record        refresh the recorded fixtures from the live sites
#
# Nothing here redirects output to /dev/null: the assertions are the point, and a
# silenced build looks exactly like a passing one.

SHELL   := /bin/bash
ROOT    := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
VENV    := $(ROOT)/.venv
PY      := $(VENV)/bin/python
# The venv's OWN pip. `$(VENV)/bin/uv pip` stood here until 2026-09-20 and named a
# binary that has never existed in this venv -- `make setup` would have failed at the
# install step, invisibly, because .venv/bin/python already existed and the rule that
# builds it never fired.
PIP     := $(PY) -m pip
FIXTURES:= $(ROOT)/tests/fixtures

# A failed single-shot fetch must not leave a truncated file that looks NEWER
# than its inputs and is therefore never retried again.
.DELETE_ON_ERROR:

# Recorded fixtures are evidence. An interrupted refresh must not destroy the
# copy we still have.
.PRECIOUS: $(FIXTURES)/%

.PHONY: all setup test test-network probe list record clean

all: test

# Built on the interpreter .tool-versions pins (asdf 3.12.9), named by path so the
# venv and the pin cannot drift. `uv venv --python 3.12` stood here and resolved to
# Homebrew's 3.12 instead.
ASDF_PY := $(HOME)/.asdf/installs/python/$(shell cut -d' ' -f2 $(ROOT)/.tool-versions)/bin/python3

$(VENV)/bin/python: $(ROOT)/.tool-versions
	@test -x "$(ASDF_PY)" || { echo "missing $(ASDF_PY) -- asdf install python $$(cut -d' ' -f2 $(ROOT)/.tool-versions)"; exit 1; }
	"$(ASDF_PY)" -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	cd $(ROOT) && $(PIP) install -e '.[dev,browser]'

setup: $(VENV)/bin/python
	@echo "env ready: $$($(PY) -V)"

test: setup
	cd $(ROOT) && $(PY) -m pytest tests/ -q

test-network: setup
	cd $(ROOT) && $(PY) -m pytest tests/ -q -m network

probe: setup
	cd $(ROOT) && $(PY) -m webgrab.cli probe

list: setup
	cd $(ROOT) && $(PY) -m webgrab.cli list

# Refresh one recorded fixture from its live site. Fixtures are evidence, so
# this is the only sanctioned way they change -- never hand-edited.
#   make record ID=fred OUT=tests/fixtures/fred_DGS10.csv
record: setup
	@test -n "$(ID)"  || { echo "usage: make record ID=<source-id> OUT=<path>"; exit 2; }
	@test -n "$(OUT)" || { echo "usage: make record ID=<source-id> OUT=<path>"; exit 2; }
	cd $(ROOT) && $(PY) -m webgrab.cli record $(ID) --out $(OUT)

clean:
	rm -rf $(ROOT)/.pytest_cache $(ROOT)/webgrab/__pycache__ $(ROOT)/tests/__pycache__
