PYTHON ?= python
VENV ?= .venv

.PHONY: install test demo clean
install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -r requirements-dev.txt
	$(VENV)/bin/python -m pip install -e .

test:
	$(VENV)/bin/python -m pytest

demo:
	bash scripts/run_demo.sh

clean:
	rm -rf .venv .pytest_cache artifacts build dist *.egg-info
