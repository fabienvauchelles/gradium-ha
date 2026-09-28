# Quality gates for gradium-ha. One Python area, one virtualenv.
#
# Home Assistant 2026.9 requires Python 3.14, which is also what the target box
# runs, so uv provisions that interpreter rather than whatever is on the system.
#
#   make build   provision .venv with Home Assistant and the test harness
#   make check   ruff + mypy + pytest, fail on any
#   make lint / typecheck / test   one step on its own

PY   := .venv/bin/python
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

PKG := custom_components/gradium
SRC := custom_components/gradium tests

.PHONY: build check lint typecheck test clean

build:
	uv python install 3.14
	uv venv --allow-existing --python 3.14 .venv
	uv pip install --python $(PY) -r requirements-test.txt ruff mypy

lint:
	$(RUFF) check $(SRC)
	$(RUFF) format --check $(SRC)

typecheck:
	$(MYPY) $(PKG)

test:
	$(PY) -m pytest tests

check: lint typecheck test

clean:
	rm -rf .venv .mypy_cache .ruff_cache .pytest_cache
	find custom_components tests -type d -name '__pycache__' -prune -exec rm -rf {} +
