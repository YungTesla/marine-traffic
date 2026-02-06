.PHONY: help build up down logs restart status shell db-backup db-stats clean

help: ## Toon beschikbare commando's
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Bouw de Docker image
	docker compose build

up: ## Start alle services
	docker compose up -d --build

down: ## Stop alle services
	docker compose down

logs: ## Bekijk live logs
	docker compose logs -f --tail=100

restart: ## Herstart alle services
	docker compose restart

status: ## Toon status van alle services
	docker compose ps

shell: ## Open een shell in de collector container
	docker compose exec ais-collector /bin/bash

db-backup: ## Maak een backup van de database
	@mkdir -p backups
	docker compose cp ais-collector:/data/encounters.db ./backups/encounters_$$(date +%Y%m%d_%H%M%S).db
	@echo "Backup opgeslagen in backups/"

db-stats: ## Toon database statistieken
	docker compose exec ais-collector python -c \
		"import sqlite3; c=sqlite3.connect('/data/encounters.db'); \
		print('Vessels:', c.execute('SELECT COUNT(*) FROM vessels').fetchone()[0]); \
		print('Positions:', c.execute('SELECT COUNT(*) FROM positions').fetchone()[0]); \
		print('Encounters:', c.execute('SELECT COUNT(*) FROM encounters').fetchone()[0])"

clean: ## Verwijder containers, images en volumes (DATA GAAT VERLOREN!)
	@echo "WAARSCHUWING: Dit verwijdert alle data inclusief de database!"
	@read -p "Weet je het zeker? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	docker compose down -v --rmi local
