.PHONY: help setup start stop restart logs clean rebuild

# Default target when running just 'make'
help:
	@echo "Available commands:"
	@echo "  make setup    - Create .env file from .env.example"
	@echo "  make start    - Start all containers"
	@echo "  make stop     - Stop all containers"
	@echo "  make restart  - Restart all containers"
	@echo "  make logs     - View container logs"
	@echo "  make clean    - Remove all containers and volumes"
	@echo "  make rebuild  - Rebuild and restart all containers"

# Create .env file if it doesn't exist
setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ".env file created from .env.example"; \
	else \
		echo ".env file already exists"; \
	fi

# Start containers
start:
	docker compose --env-file .env up -d

# Stop containers
stop:
	docker compose --env-file .env down

# Restart containers
restart:
	docker compose --env-file .env restart

# View logs
logs:
	docker compose --env-file .env logs -f

# Clean everything
clean:
	docker compose --env-file .env down -v
	rm -f .env

# Rebuild and restart
rebuild:
	docker compose --env-file .env down
	docker compose --env-file .env build --no-cache
	docker compose --env-file .env up -d 