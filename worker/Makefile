.PHONY: help install install-dev test lint fmt run once

help:
	@echo "install      install runtime dependencies"
	@echo "install-dev  install runtime + dev dependencies"
	@echo "test         run the unit tests (no network, no weights, no GPU)"
	@echo "lint         ruff check"
	@echo "fmt          ruff format + autofix"
	@echo "run          start the scheduler loop"
	@echo "once         capture every active hall exactly once and exit"

install:
	python -m pip install -e .

install-dev:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .
	python -m ruff format --check .

fmt:
	python -m ruff check --fix .
	python -m ruff format .

run:
	python -m hallcheck.cli run

once:
	python -m hallcheck.cli once
