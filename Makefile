isort := isort
black := black
autoflake := autoflake

AUTOFLAKE_ARGS := -r --ignore-init-module-imports --expand-star-imports --remove-all-unused-imports --remove-duplicate-keys -i

format:
	$(autoflake) server $(AUTOFLAKE_ARGS)
	$(isort) server tests *.py
	$(black) --experimental-string-processing server tests *.py


prepare:
	pre-commit install

lint:
	#flake8 pydantic/ tests/ main.py
	$(isort) --check-only --df .
	$(black) --check --diff
