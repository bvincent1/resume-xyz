SHELL := /bin/bash

COMPOSE ?= docker compose
COMPOSE_PROJECT ?= resume-xyz-e2e
COMPOSE_FILE := docker-compose.yaml
COMPOSE_CMD := $(COMPOSE) -p $(COMPOSE_PROJECT) -f $(COMPOSE_FILE)

E2E_POSTGRES_URL ?= postgres://postgres:postgres@127.0.0.1:55432/resume_e2e
RESUME_SERVICE_HOST ?= http://127.0.0.1:3001
DJANGO_DIR := ../application_manager
DJANGO := cd $(DJANGO_DIR) && E2E_STUBS=1 E2E_POSTGRES_URL='$(E2E_POSTGRES_URL)' RESUME_SERVICE_HOST='$(RESUME_SERVICE_HOST)' TINYFISH_API_KEY=e2e poetry run python manage.py
PLAYWRIGHT_ARGS ?=

.PHONY: install browsers up down migrate seed test test-headed

install:
	pnpm install --frozen-lockfile

browsers:
	pnpm exec playwright install --with-deps chromium

up:
	$(COMPOSE_CMD) up -d --wait postgres resume

down:
	$(COMPOSE_CMD) down -v --remove-orphans

migrate:
	$(DJANGO) migrate --settings=application_manager.settings_e2e --noinput

seed:
	$(DJANGO) seed_e2e --settings=application_manager.settings_e2e

test: up migrate
	$(DJANGO) flush --settings=application_manager.settings_e2e --noinput
	$(DJANGO) seed_e2e --settings=application_manager.settings_e2e
	E2E_POSTGRES_URL='$(E2E_POSTGRES_URL)' RESUME_SERVICE_HOST='$(RESUME_SERVICE_HOST)' pnpm exec playwright test $(PLAYWRIGHT_ARGS)

test-headed: PLAYWRIGHT_ARGS = --headed
test-headed: test
