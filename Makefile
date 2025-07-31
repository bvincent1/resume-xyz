#!make
SHELL:=/bin/bash

include .env
export $(shell sed 's/=.*//' .env)

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

services:
	@docker compose -f tools/compose/development.yml --env-file .env -p reactive-resume up
.PHONY: services


backup:
	@cd application_manager && make backup
.PHONY: backup