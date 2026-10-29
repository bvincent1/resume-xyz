
# Forcibly build and (re)run all the services in the background. Loads any env changes into services.
compose:
	@docker compose up -d --force-recreate
.PHONY: compose

