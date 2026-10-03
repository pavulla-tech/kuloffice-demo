# KulPay deployment: the whole stack on one server. `make help`.
#
# On the laptop: make images && make push (Docker Hub), make license.
# On the server:  make setup, fill .env, make config, make start, make init.

.PHONY: help setup sync-env clean-env-backups config check-images \
        images push theme license \
        start start-portal stop restart logs ps update clean \
        init operator

ENV_FILE ?= .env
ENV_EXAMPLE ?= .env.example
COMPOSE = ENV_FILE=$(ENV_FILE) docker compose --env-file $(ENV_FILE)

# A service, for the targets that take one: make logs S=kuloffice
S ?=

# Every image `make images` builds, by its .env prefix.
IMAGES = KEYCLOAK KULOFFICE WEB FILESERVER TOKEN_PANEL TOOLS SOLANGE SOLANGE_CONSOLE

help:
	@echo "Setup"
	@echo "  make setup              create .env from .env.example"
	@echo "  make sync-env           reorder .env to match the example, comment stale vars"
	@echo "  make clean-env-backups  remove the backups sync-env leaves"
	@echo "  make config             check .env and render the compose configuration"
	@echo "  make check-images       refuse two services sharing one image ref"
	@echo ""
	@echo "Images (on the laptop)"
	@echo "  make images [S=WEB]     build every image (or one) for TARGET_PLATFORM"
	@echo "  make push [S=WEB]       push them to Docker Hub (docker login first)"
	@echo "  make theme              copy intaka's login theme into theme/ (commit it)"
	@echo "  make license            print a kuloffice license key (KULOFFICE_DIR/keys)"
	@echo ""
	@echo "Run (on the server)"
	@echo "  make start              start the stack"
	@echo "  make start-portal       also start kulportal (needs KULPORTAL_TAG)"
	@echo "  make stop / ps / logs [S=x]"
	@echo "  make restart [S=x]      recreate everything, or one service (reloads .env)"
	@echo "  make update             pull the tags in .env and recreate what changed"
	@echo "  make clean              remove containers AND volumes (every database)"
	@echo ""
	@echo "Provisioning (on the server, after start)"
	@echo "  make init               realms, clients, kuloffice license and identity providers"
	@echo "  make operator EMAIL=… FIRST=… LAST=… [ROLE=Revisores] [SOLANGE=viewer,developer]"
	@echo "                          a staff account; ROLE= (empty) for Solange only"

# ── setup ─────────────────────────────────────────────────────────────────────

setup:
	@if [ ! -f "$(ENV_FILE)" ]; then \
		cp "$(ENV_EXAMPLE)" "$(ENV_FILE)"; chmod 600 "$(ENV_FILE)"; \
		echo "$(ENV_FILE) created from $(ENV_EXAMPLE) - fill in the empty values"; \
	else \
		echo "$(ENV_FILE) already exists (make sync-env brings it up to date)"; \
	fi
	@[ -f kuloffice.env ] || { cp kuloffice.env.example kuloffice.env; chmod 600 kuloffice.env; echo "kuloffice.env created"; }

sync-env:
	@sh scripts/organize-env.sh "$(ENV_FILE)" "$(ENV_EXAMPLE)"

clean-env-backups:
	@n=$$(find . -maxdepth 1 -type f -name "$$(basename $(ENV_FILE)).backup.*" | wc -l | tr -d ' '); \
	find . -maxdepth 1 -type f -name "$$(basename $(ENV_FILE)).backup.*" -delete; \
	echo "Removed $$n backups of $(ENV_FILE)"

config: check-images
	$(COMPOSE) config --quiet && echo "configuration is complete"

check-images:
	@sh scripts/check-image-refs.sh "$(ENV_FILE)" $(IMAGES) MINIO MC

# ── images (laptop) ───────────────────────────────────────────────────────────

# How each image is built: context, Dockerfile, extra build contexts and args.
# Paths in .env are relative to this directory.
build_KEYCLOAK        = docker build --platform $$TARGET_PLATFORM -t "$$KEYCLOAK_IMAGE:$$KEYCLOAK_TAG" "$$INTAKA_DIR"
build_KULOFFICE       = key=$$(cat "$$KULOFFICE_DIR/keys/public.pem.base64") || exit 1; \
	docker build --platform $$TARGET_PLATFORM -t "$$KULOFFICE_IMAGE:$$KULOFFICE_TAG" \
	  -f images/kuloffice.Dockerfile --build-arg LICENSE_PUBLIC_KEY="$$key" "$$KULOFFICE_DIR"
build_WEB             = docker build --platform $$TARGET_PLATFORM -t "$$WEB_IMAGE:$$WEB_TAG" -f images/web.Dockerfile "$$WEB_DIR"
build_FILESERVER      = docker build --platform $$TARGET_PLATFORM -t "$$FILESERVER_IMAGE:$$FILESERVER_TAG" -f images/fileserver.Dockerfile "$$FILESERVER_DIR"
build_TOKEN_PANEL     = docker build --platform $$TARGET_PLATFORM -t "$$TOKEN_PANEL_IMAGE:$$TOKEN_PANEL_TAG" -f images/token-panel.Dockerfile \
	  --build-context stack=../stack "$$INTAKA_DIR/demo/token-panel"
build_TOOLS           = docker build --platform $$TARGET_PLATFORM -t "$$TOOLS_IMAGE:$$TOOLS_TAG" -f images/tools.Dockerfile \
	  --build-context stack=../stack --build-context tools=tools "$$INTAKA_DIR/demo/setup"
build_SOLANGE         = docker build --platform $$TARGET_PLATFORM -t "$$SOLANGE_IMAGE:$$SOLANGE_TAG" -f images/solange.Dockerfile "$$SOLANGE_DIR"
build_SOLANGE_CONSOLE = docker build --platform $$TARGET_PLATFORM -t "$$SOLANGE_CONSOLE_IMAGE:$$SOLANGE_CONSOLE_TAG" -f images/solange-console.Dockerfile "$$SOLANGE_DIR/console"
build_KULPORTAL       = docker build --platform $$TARGET_PLATFORM -t "$$KULPORTAL_IMAGE:$$KULPORTAL_TAG" "$$KULPORTAL_DIR"

images: check-images
	@set -a; . ./$(ENV_FILE); set +a; set -e; \
	for name in $(or $(S),$(IMAGES)); do \
		eval "tag=\$${$${name}_TAG}"; [ -n "$$tag" ] || { echo "$${name}_TAG is empty in $(ENV_FILE)" >&2; exit 1; }; \
		echo "== $$name"; \
		case $$name in \
		KEYCLOAK) $(build_KEYCLOAK) ;; KULOFFICE) $(build_KULOFFICE) ;; WEB) $(build_WEB) ;; \
		FILESERVER) $(build_FILESERVER) ;; TOKEN_PANEL) $(build_TOKEN_PANEL) ;; TOOLS) $(build_TOOLS) ;; \
		SOLANGE) $(build_SOLANGE) ;; SOLANGE_CONSOLE) $(build_SOLANGE_CONSOLE) ;; KULPORTAL) $(build_KULPORTAL) ;; \
		*) echo "unknown image $$name" >&2; exit 1 ;; \
		esac; \
	done

push: check-images
	@set -a; . ./$(ENV_FILE); set +a; set -e; \
	for name in $(or $(S),$(IMAGES)); do \
		eval "ref=\$${$${name}_IMAGE}:\$${$${name}_TAG}"; echo "== $$ref"; docker push "$$ref"; \
	done

# The login theme Keycloak mounts, from intaka's checkout. Commit the result:
# the server has no intaka checkout.
theme:
	@set -a; . ./$(ENV_FILE); set +a; \
	rm -rf theme && mkdir -p theme && cp -R "$$INTAKA_DIR/demo/theme/kulpay" theme/ && \
	echo "theme/kulpay copied from $$INTAKA_DIR/demo/theme (commit it)"

# A license key for KULOFFICE_LICENSE_KEY, signed with kuloffice's private key.
license:
	@set -a; . ./$(ENV_FILE); set +a; \
	$(MAKE) --no-print-directory -C "$$KULOFFICE_DIR" generate-license >/dev/null && cat "$$KULOFFICE_DIR/keys/license.key"; echo

# ── run (server) ──────────────────────────────────────────────────────────────

start: check-images
	$(COMPOSE) up -d

start-portal: check-images
	@set -a; . ./$(ENV_FILE); set +a; [ -n "$${KULPORTAL_TAG:-}" ] || { echo "KULPORTAL_TAG is empty in $(ENV_FILE)" >&2; exit 1; }
	$(COMPOSE) --profile portal up -d

stop:
	$(COMPOSE) --profile portal down

# Recreates: a plain restart keeps a container's old environment.
restart:
	$(COMPOSE) up -d --force-recreate $(S)

logs:
	$(COMPOSE) --profile portal logs -f --tail=200 $(S)

ps:
	$(COMPOSE) --profile portal ps -a

update: check-images
	$(COMPOSE) pull --ignore-pull-failures
	$(COMPOSE) up -d

# Destroys every database: Keycloak's users and passkeys, kuloffice's accounts,
# Solange's codes, and the files in MinIO.
clean:
	@printf 'This deletes every database and every stored file. Type DESTROY to continue: '; \
	read answer; [ "$$answer" = "DESTROY" ] || { echo "aborted"; exit 1; }
	$(COMPOSE) --profile portal --profile tools down -v

# ── provisioning (server) ─────────────────────────────────────────────────────

init:
	$(COMPOSE) --profile tools run --rm tools /tools/init.sh

ROLE ?= Revisores
SOLANGE ?=
operator:
	@[ -n "$(EMAIL)" ] || { echo "usage: make operator EMAIL=… FIRST=… LAST=… [ROLE=Revisores] [SOLANGE=viewer]" >&2; exit 1; }
	$(COMPOSE) --profile tools run --rm -e STAFF_EMAIL="$(EMAIL)" -e STAFF_FIRST_NAME="$(FIRST)" -e STAFF_LAST_NAME="$(LAST)" \
		-e KULOFFICE_ROLE="$(ROLE)" -e SOLANGE_ROLES="$(SOLANGE)" tools /tools/operator.sh
