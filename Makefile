.PHONY: up up-prod down test test-prod format shell build-dev build-prod rmi-dev rmi-prod update-deps clean

MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

up:
	docker compose up cc_logger

up-prod:
	docker compose up cc_logger_prod

down:
	docker compose down

test:
	docker compose run --rm --no-deps cc_logger python -m unittest discover -s tests -v

test-prod:
	docker compose run --rm --no-deps \
		-v $(MAKEFILE_DIR)tests:/app/tests:ro \
		cc_logger_prod python -m unittest discover -s tests -v

format:
	docker compose run --rm --no-deps cc_logger python -m black .

shell:
	docker compose run --rm cc_logger /bin/sh

build-dev:
	docker compose build cc_logger

build-prod:
	docker compose build cc_logger_prod

rmi-dev:
	docker image rm cc-logger:dev

rmi-prod:
	docker image rm cc-logger:prod

update-deps:
	uv lock --upgrade
	docker compose build cc_logger

clean:
	docker compose down --remove-orphans
	-docker image rm cc-logger:dev
	-docker image rm cc-logger:prod
