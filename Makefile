isort := isort
black := black
autoflake := autoflake
VERSION := $(shell scripts/get_version.py)
UI_VERSION := 0.2.4
AUTOFLAKE_ARGS := -r --ignore-init-module-imports --expand-star-imports --remove-all-unused-imports --remove-duplicate-keys -i

init:
	pre-commit install
	sudo apt install gettextm

format:
	$(autoflake) server $(AUTOFLAKE_ARGS)
	$(isort) server tests *.py
	$(black) --experimental-string-processing server tests *.py


lint:
	flake8 server/ tests/ main.py
	$(isort) --check-only --df .
	$(black) --check --diff

docker-image__main:
	@echo "Building docker image telephonist:$(VERSION)"
	sudo docker build -t maratbr/telephonist:$(VERSION) -t maratbr/telephonist:latest .

docker-image__allinone:
	@echo "Building docker image telephonist-all-in-one:$(VERSION)"
	sudo docker build \
		-t maratbr/telephonist-all-in-one:$(VERSION) \
		-t maratbr/telephonist-all-in-one:latest \
		-f ./AllInOne.dockerfile \
		.


docker-image: mo format docker-image__main docker-image__allinone


run-docker-image:
	sudo docker run \
		--name telephonist-test-run-$(VERSION) \
		-e TELEPHONIST_BACKPLANE_BACKEND=memory \
		-e TELEPHONIST_DISABLE_SSL=True \
		telephonist:$(VERSION)

publish:
	sudo docker push maratbr/telephonist:$(VERSION)
	sudo docker push maratbr/telephonist:latest
	sudo docker push maratbr/telephonist-all-in-one:$(VERSION)
	sudo docker push maratbr/telephonist-all-in-one:latest

run-non-secure-all-in-one:
	cd ./docker; SECRET=not_a_secret_obviosly docker-compose up

build-and-run-docker-image: docker-image run-docker-image

regenerate-po-files:
	mkdir -p locales/en/LC_MESSAGES
	pygettext3 -v -p locales/en/LC_MESSAGES ./server/

	mkdir -p locales/ru/LC_MESSAGES
	pygettext3 -v -p locales/ru/LC_MESSAGES ./server/

mo:
	msgfmt -o locales/ru/LC_MESSAGES/messages.mo locales/ru/LC_MESSAGES/messages.pot
	msgfmt -o locales/en/LC_MESSAGES/messages.mo locales/en/LC_MESSAGES/messages.pot

