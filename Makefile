isort := isort
black := black

format:
	$(isort) server tests main.py
	$(black) server tests main.py

prepare:
	pre-commit install

lint:
	#flake8 pydantic/ tests/ main.py
	$(isort) --check-only --df .
	$(black) --check --diff
