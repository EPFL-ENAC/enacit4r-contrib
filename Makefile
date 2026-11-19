venv:
	uv sync --all-extras

test: venv
	uv run pytest tests/ -q

lint: venv
	uv run ruff check . && uv run ruff format --check .

build: venv
	uv build

docs:
	uv run zensical serve

docs-build:
	uv run zensical build --clean --strict
