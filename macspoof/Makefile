PYTHON ?= python3
VENV   ?= .venv
PREFIX ?= $(HOME)/.local

.PHONY: help install dev test lint clean run

help:
	@echo "macspoof - MAC address spoofer"
	@echo ""
	@echo "  make install   install into a venv at $(VENV)"
	@echo "  make dev       install in editable mode into $(VENV)"
	@echo "  make test      run the test suite"
	@echo "  make run       run the CLI (ARGS=\"list\")"
	@echo "  make clean     remove build artifacts"

# --system-site-packages is required so the venv can see PyGObject, which is
# provided by the system package manager on most distributions.
$(VENV):
	$(PYTHON) -m venv --system-site-packages $(VENV)

install: $(VENV)
	$(VENV)/bin/pip install .

dev: $(VENV)
	$(VENV)/bin/pip install -e .

test: $(VENV)
	$(VENV)/bin/pip install -q -e . || true
	$(PYTHON) -m unittest discover -s tests -v

run:
	$(PYTHON) -m macspoof $(ARGS)

clean:
	rm -rf build dist *.egg-info $(VENV)/lib/*/site-packages/macspoof*
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
