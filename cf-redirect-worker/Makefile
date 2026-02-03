
include ../.env
export $(shell sed 's/=.*//' .env)

install: ## install deps
	@pnpm install
.PHONY: install

deploy: ## deploy worker
	@pnpm run deploy
.PHONY: deploy

DB_CONNECTION=postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@$(POSTGRES_HOST):$(POSTGRES_PORT)/$(POSTGRES_DB)
dev: ## run dev server
	@CLOUDFLARE_HYPERDRIVE_LOCAL_CONNECTION_STRING_HYPERDRIVE="$(DB_CONNECTION)" pnpm run dev
.PHONY: dev

types:
	@pnpm run cf-typegen
.PHONY: types

