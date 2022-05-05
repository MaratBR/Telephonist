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
	sudo docker build -t maratbr/telephonist:$(VERSION) -t maratbr/telephonist:latest .

run-docker-image:
	sudo docker run \
		--name telephonist-test-run-$(VERSION) \
		-e TELEPHONIST_BACKPLANE_BACKEND=memory \
		-e TELEPHONIST_DISABLE_SSL=True \
		telephonist:$(VERSION)

publish:
	sudo docker push maratbr/telephonist:$(VERSION)
	sudo docker push maratbr/telephonist:latest

run-non-secure-all-in-one:
	cd ./docker; SECRET=not_a_secret_obviosly docker-compose up

build-and-run-docker-image: docker-image run-docker-image