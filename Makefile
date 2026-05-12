.PHONY: test lint run install-dev clean

install-dev:
	pip install -e ".[dev]"

test:
	pytest -v

lint:
	ruff check . && mypy braiins_hashpower_mcp/

run:
	python -m braiins_hashpower_mcp.server

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
