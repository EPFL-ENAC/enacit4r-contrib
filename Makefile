venv:
	uv sync --all-extras

test: venv
	uv run pytest tests/ -q

lint: venv
	uv run ruff check . && uv run ruff format --check .

build: venv
	uv build
