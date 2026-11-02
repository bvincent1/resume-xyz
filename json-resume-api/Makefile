#!make
SHELL:=/bin/bash

install: ## install dependencies
	@pnpm install
.PHONY: install

dev: ## run the server
	@pnpm nodemon src/index.js
.PHONY: dev

test: ## run the route tests
	@pnpm test
.PHONY: test

clean: ## remove generated documents from the public dir
	@rm -f public/*.pdf public/*.html
.PHONY: clean

prod:
	@nohup make dev
	@echo "" > nohup.out
	@nohup pnpm nodemon src/index.js &
.PHONY: prod
