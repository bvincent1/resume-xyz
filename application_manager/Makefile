#!make
SHELL:=/bin/bash

include .env
export $(shell sed 's/=.*//' .env)

DJANGO=poetry run python manage.py

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
	@$(DJANGO) shell
.PHONY: shell

services:
	@docker compose -f ./docker-compose.yml --env-file .env up
.PHONY: services


scheduler:
	@poetry run celery -A django_api beat -l INFO  --scheduler django_celery_beat.schedulers:DatabaseScheduler
.PHONY: scheduler


worker:
	@poetry run celery -A django_api worker -l INFO
.PHONY: worker

pdfs:
	@$(DJANGO) generate_pdfs
.PHONY: pdfs

prompts:
	@$(DJANGO) regen_prompts
.PHONY: prompts


dumpdata:
	@$(DJANGO) dumpdata -o mydata.json.gz
.PHONY: dumpdata


prod:
	@echo "" > nohup.out
	@nohup $(DJANGO) runserver 0.0.0.0:9099 &
.PHONY: prod