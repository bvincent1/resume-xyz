#!make
SHELL:=/bin/bash

include .env
export $(shell sed 's/=.*//' .env)

# DJANGO=poetry run python manage.py
# CELERY=poetry run python -m celery

install: ## install reactive resume deps
	@pnpm install
.PHONY: install

init: ## init connected postgres DB
	@pnpm prisma:migrate:dev
.PHONY: init

build: ## build reactive resume project
	@pnpm build
.PHONY: build

app: ## run the reactive resume build output, contains FE, and PDF builder in one server
	@npm run start
.PHONY: app

django: ## runt he django admin interface
	@cd application_manager && make dev
.PHONY: django

services: ## run the dep-services on docker compose
	@docker compose -f tools/compose/development.yml --env-file .env -p reactive-resume up --build
.PHONY: services

local: build-local ## run the whole system on docker compose
	@docker compose -f tools/compose/local.yml --env-file .env -p reactive-resume up
.PHONY: local

backup: ## run the backup script and output to [backup.tar](./applications_manager/backup.tar)
	@cd application_manager && make backup
.PHONY: backup

scheduler:
	@cd application_manager && make scheduler
.PHONY: scheduler

worker:
	@cd application_manager && make worker
.PHONY: worker

build-local: ## build local compose containers
	@docker compose -f tools/compose/local.yml build
.PHONY: build-local
