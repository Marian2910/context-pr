.RECIPEPREFIX := >

.PHONY: install lint format typecheck test ci run-help

install:
>python -m pip install --upgrade pip
>python -m pip install -e ".[dev]"

lint:
>ruff check .
>ruff format --check .

format:
>ruff check . --fix
>ruff format .

typecheck:
>mypy src tests

test:
>pytest

ci:
>ruff check .
>ruff format --check .
>mypy src tests
>pytest

run-help:
>python -m contextpr --help
