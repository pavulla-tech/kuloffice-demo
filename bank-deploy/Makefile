ENV_FILE ?= .env
COMPOSE = docker compose --env-file $(ENV_FILE) -f compose.yaml
S ?=
ROLE ?= Revisores
SOLANGE ?=

.PHONY: help setup config pull start stop restart ps logs provision operator qr-provision gateway-provision health backup

help:
	@echo "KulPay bank deployment"
	@echo "  make setup                 create protected environment files"
	@echo "  make config                validate settings and render Compose"
	@echo "  make pull                  pull the pinned images"
	@echo "  make start                 start production services"
	@echo "  make provision             realms, clients, identities and licenses"
	@echo "  make operator EMAIL=... FIRST=... LAST=... [ROLE=Revisores|ADMIN]"
	@echo "  make qr-provision          provision KulOffice in Solange"
	@echo "  make gateway-provision     provision signed Gateway event delivery"
	@echo "  make health                run installation acceptance checks"
	@echo "  make ps / make logs S=x"
	@echo "  make restart [S=x]         recreate services and reload environment"
	@echo "  make backup                write PostgreSQL and MinIO backups"
	@echo "  make stop                  stop containers and preserve data"

setup:
	@test -f $(ENV_FILE) || { cp .env.example $(ENV_FILE); chmod 600 $(ENV_FILE); echo "created $(ENV_FILE)"; }
	@test -f kuloffice.env || { cp kuloffice.env.example kuloffice.env; chmod 600 kuloffice.env; echo "created kuloffice.env"; }

config:
	@ENV_FILE=$(ENV_FILE) sh scripts/check-config.sh
	@$(COMPOSE) config --quiet
	@echo "configuration is valid"

pull: config
	$(COMPOSE) pull

start: config
	$(COMPOSE) up -d

stop:
	$(COMPOSE) --profile provisioning down

restart: config
	$(COMPOSE) up -d --force-recreate $(S)

ps:
	$(COMPOSE) --profile provisioning ps -a

logs:
	$(COMPOSE) logs --tail=200 -f $(S)

provision: config
	$(COMPOSE) --profile provisioning run --rm provisioner /bank/init.sh

operator: config
	@test -n "$(EMAIL)" -a -n "$(FIRST)" -a -n "$(LAST)" || { echo "EMAIL, FIRST and LAST are required" >&2; exit 2; }
	$(COMPOSE) --profile provisioning run --rm \
		-e STAFF_EMAIL="$(EMAIL)" -e STAFF_FIRST_NAME="$(FIRST)" -e STAFF_LAST_NAME="$(LAST)" \
		-e KULOFFICE_ROLE="$(ROLE)" -e SOLANGE_ROLES="$(SOLANGE)" \
		provisioner /tools/operator.sh

qr-provision: config
	@ENV_FILE=$(ENV_FILE) COMPOSE="$(COMPOSE)" sh scripts/provision-qr.sh

gateway-provision: config
	@ENV_FILE=$(ENV_FILE) COMPOSE="$(COMPOSE)" sh scripts/provision-gateway.sh

health:
	@ENV_FILE=$(ENV_FILE) COMPOSE="$(COMPOSE)" sh scripts/health.sh

backup:
	@ENV_FILE=$(ENV_FILE) COMPOSE="$(COMPOSE)" sh scripts/backup.sh
