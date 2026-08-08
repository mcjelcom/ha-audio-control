.PHONY: help setup lint format typecheck test ci

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## One-time: create the venv and install dev deps
	uv venv --python 3.12
	.venv/bin/pip install -r requirements-dev.txt

lint:  ## ruff check
	.venv/bin/ruff check custom_components/audio_control/ tests/

format:  ## ruff format
	.venv/bin/ruff format custom_components/audio_control/ tests/

format-check:  ## ruff format --check
	.venv/bin/ruff format --check custom_components/audio_control/ tests/

typecheck:  ## mypy --strict
	.venv/bin/python -m mypy --strict custom_components/audio_control/

test:  ## pytest
	.venv/bin/python -m pytest tests/ -q

ci: lint format-check typecheck test  ## Full gate
	@echo "\n✅ All checks passed"
