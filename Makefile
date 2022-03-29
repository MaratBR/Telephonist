isort := isort
black := black
autoflake := autoflake
VERSION := $(shell scripts/get_version.py)
AUTOFLAKE_ARGS := -r --ignore-init-module-imports --expand-star-imports --remove-all-unused-imports --remove-duplicate-keys -i

format:
	$(autoflake) server $(AUTOFLAKE_ARGS)
	$(isort) server tests *.py
	$(black) --experimental-string-processing server tests *.py


prepare:
	pre-commit install

lint:
	flake8 server/ tests/ main.py
	$(isort) --check-only --df .
	$(black) --check --diff

docker-image:
	@echo "Building docker image telephonist:$(VERSION)"
	docker build -t telephonist:$(VERSION) -t telephonist:latest .

run-docker-image:
	docker run \
		--name telephonist-test-run-$(VERSION) \
		-e TELEPHONIST_BACKPLANE_BACKEND=memory \
		-e TELEPHONIST_SESSION_BACKEND=memory \
		-e TELEPHONIST_DISABLE_SSL=True \
		telephonist:$(VERSION)


build-and-run-docker-image: docker-image run-docker-image