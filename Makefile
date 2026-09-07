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
PIP     := $(VENV)/bin/uv pip
FIXTURES:= $(ROOT)/tests/fixtures

# A failed single-shot fetch must not leave a truncated file that looks NEWER
# than its inputs and is therefore never retried again.
.DELETE_ON_ERROR:

# Recorded fixtures are evidence. An interrupted refresh must not destroy the
# copy we still have.
.PRECIOUS: $(FIXTURES)/%

.PHONY: all setup test test-network probe list record clean

all: test

$(VENV)/bin/python:
	uv venv --python 3.12 $(VENV)
	cd $(ROOT) && $(PIP) install -e '.[dev]'

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
