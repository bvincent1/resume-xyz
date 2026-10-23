#!make
SHELL:=/bin/bash

install: ## install dependencies
	@pnpm install
.PHONY: install

dev: ## run the server
	@pnpm nodemon src/index.js
.PHONY: dev

clean: ## remove generated PDFs from the public dir
	@rm -f public/*.pdf
.PHONY: clean
