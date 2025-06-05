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

run: ## run the reactive resume build output, contains FE, and PDF builder in one server
	@node dist/apps/server/main.js
.PHONY: run

services:
	@docker compose -f tools/compose/development.yml --env-file .env -p reactive-resume up
.PHONY: services