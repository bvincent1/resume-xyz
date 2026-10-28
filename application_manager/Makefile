#!make
SHELL:=/bin/bash

include .env
export $(shell sed 's/=.*//' .env)

DJANGO=poetry run python manage.py
CELERY=poetry run python -m celery

install:
	@poetry install
.PHONY: install


migrations:
	@$(DJANGO) makemigrations accounts
	@$(DJANGO) makemigrations job_applications
	@$(DJANGO) migrate
.PHONY: migrations

# - see [.env](./.env) for admin pass
seed: migrations
	@$(DJANGO) createsuperuser --no-input --email admin@admin.ca
.PHONY: seed

dev:
	@$(DJANGO) runserver 0.0.0.0:9099
.PHONY: dev

shell:
	@$(DJANGO) shell_plus --bpython
.PHONY: shell

services:
	@docker compose -f ./docker-compose.yml --env-file .env up
.PHONY: services


scheduler:
	@$(CELERY) -A application_manager beat -l INFO  --scheduler django_celery_beat.schedulers:DatabaseScheduler
.PHONY: scheduler


worker:
	@env
	@$(CELERY) -A application_manager worker -l INFO
.PHONY: worker


tests:
	@docker run --rm -d --name resume-test-pg \
		-e POSTGRES_PASSWORD=postgres -p 5459:5432 postgres:16-alpine
	@POSTGRES_URL="postgres://postgres:postgres@localhost:5459/postgres" \
		$(DJANGO) test job_applications -v 2
.PHONY: tests

backup:
	@pg_dump -a -O -f backup.tar -Ft -d $(DB_CONNECTION)
.PHONY: backup


prod:
	@echo "" > application.log
	@nohup $(DJANGO) runserver 0.0.0.0:9099 > application.log 2>&1 &
.PHONY: prod
