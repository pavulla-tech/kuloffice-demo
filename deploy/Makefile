# KulPay deployment: the whole stack on one server. `make help`.
#
# On the laptop: make images && make push (Docker Hub), make license.
# On the server:  make setup, fill .env, make config, make start, make init.

.PHONY: help setup sync-env clean-env-backups config check-images \
        images push bundle load theme license \
        start start-portal start-website stop restart logs ps update clean reset-blnk \
        init operator gateway-signin solange-kulpay gateway-kuloffice cash-deposits gateway-billers simulator-bank \
        deploy rollback releases status health backup restore

ENV_FILE ?= .env
ENV_EXAMPLE ?= .env.example
COMPOSE = ENV_FILE=$(ENV_FILE) docker compose --env-file $(ENV_FILE)

# A service, for the targets that take one: make logs S=kuloffice (F=0 to print and exit)
S ?=

# Every image `make images` builds, by its .env prefix.
IMAGES = KEYCLOAK KULOFFICE WEB FILESERVER TOKEN_PANEL TOOLS SOLANGE SOLANGE_CONSOLE GATEWAY SIMULATOR

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
	@echo "  make bundle [S=…]       build the gateway and simulator into one archive for scp"
	@echo "  make theme              copy intaka's login theme into theme/ (commit it)"
	@echo "  make license            print a kuloffice license key (KULOFFICE_DIR/keys)"
	@echo ""
	@echo "Run (on the server)"
	@echo "  make start              start the stack"
	@echo "  make start-portal       also start kulportal (needs KULPORTAL_TAG)"
	@echo "  make start-website      also start the website (needs WEBSITE_TAG)"
	@echo "  make stop / ps / logs [S=x]"
	@echo "  make restart [S=x]      recreate everything, or one service (reloads .env)"
	@echo "  make update             pull the tags in .env and recreate what changed"
	@echo "  make load FILE=…        load a bundle's images (make bundle on the laptop)"
	@echo ""
	@echo "Releases (on the server; CI runs the same tool, bin/kulpay)"
	@echo "  make deploy U=web T=v0.1.0-alpha02   switch a unit to a tag (health-checked)"
	@echo "  make rollback U=web [STEPS=1 | TO=tag] [YES=1]"
	@echo "  make releases [U=web]   what ran, and the last attempts"
	@echo "  make status             each unit's current tag"
	@echo "  make health [U=web]     check the running units"
	@echo "  make backup DB=kuloffice / make restore DB=kuloffice FILE=… YES=1"
	@echo "  make clean              remove containers AND volumes (every database)"
	@echo "  make reset-blnk YES=DESTROY  back up and rebuild only BLNK's complete ledger"
	@echo ""
	@echo "Provisioning (on the server, after start)"
	@echo "  make init               realms, clients, kuloffice license and identity providers"
	@echo "  make gateway-kuloffice  Gateway event endpoints and signing secrets for KulOffice"
	@echo "  make platform-wallet    KulPay balance at the Gateway checkout for KulPay's own purchases"
	@echo "  make cash-deposits      partner cash deposits credit KulPay accounts (live; dev only)"
	@echo "  make gateway-billers    billers approved in the back office provisioned at the Gateway"
	@echo "  make simulator-bank     the PSP simulator as a certified partner bank (SIMBANK=plan|apply|rollback)"
	@echo "  make operator EMAIL=… FIRST=… LAST=… [ROLE=Revisores|ADMIN] [SOLANGE=viewer,developer] [GATEWAY=1]"
	@echo "                          ROLE=ADMIN: the Administradores role (every kuloffice permission)"
	@echo "                          a staff account; ROLE= (empty) for Solange only"
	@echo "  make solange-kulpay     KulPay's app in Solange, kuloffice's key and webhook (into .env)"

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
	@sh scripts/check-image-refs.sh "$(ENV_FILE)" $(IMAGES) KULPORTAL WEBSITE MINIO MC

# ── images (laptop) ───────────────────────────────────────────────────────────

# How each image is built: context, Dockerfile, extra build contexts and args.
# Paths in .env are relative to this directory.
# Keycloak: intaka's image, then the login theme on top (images/keycloak.Dockerfile).
build_KEYCLOAK        = docker build --platform $$TARGET_PLATFORM -t "kulpay-keycloak-base:$$KEYCLOAK_TAG" "$$INTAKA_DIR" && \
	docker build --platform $$TARGET_PLATFORM -t "$$KEYCLOAK_IMAGE:$$KEYCLOAK_TAG" -f images/keycloak.Dockerfile \
	  --build-arg BASE="kulpay-keycloak-base:$$KEYCLOAK_TAG" "$$INTAKA_DIR/demo/theme"
# The license public key is kept here (keys/), so CI and laptops link the same
# one: the key the server's KULOFFICE_LICENSE_KEY was signed for.
build_KULOFFICE       = key=$$(cat keys/kuloffice-license.pub.base64) || exit 1; \
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
# The website's links and social cards carry its public address.
build_WEBSITE         = docker build --platform $$TARGET_PLATFORM -t "$$WEBSITE_IMAGE:$$WEBSITE_TAG" -f images/website.Dockerfile \
	  --build-arg BASE_URL="$$WEBSITE_PUBLIC_URL/" "$$WEBSITE_DIR"
# The payments gateway and the PSP simulator build from their repositories' own
# Dockerfiles.
build_GATEWAY         = docker build --platform $$TARGET_PLATFORM -t "$$GATEWAY_IMAGE:$$GATEWAY_TAG" "$$GATEWAY_DIR"
build_SIMULATOR       = docker build --platform $$TARGET_PLATFORM -t "$$SIMULATOR_IMAGE:$$SIMULATOR_TAG" "$$SIMULATOR_DIR"

images: check-images
	@set -a; . ./$(ENV_FILE); set +a; set -e; \
	for name in $(or $(S),$(IMAGES)); do \
		eval "tag=\$${$${name}_TAG}"; [ -n "$$tag" ] || { echo "$${name}_TAG is empty in $(ENV_FILE)" >&2; exit 1; }; \
		echo "== $$name"; \
		case $$name in \
		KEYCLOAK) $(build_KEYCLOAK) ;; KULOFFICE) $(build_KULOFFICE) ;; WEB) $(build_WEB) ;; \
		FILESERVER) $(build_FILESERVER) ;; TOKEN_PANEL) $(build_TOKEN_PANEL) ;; TOOLS) $(build_TOOLS) ;; \
		SOLANGE) $(build_SOLANGE) ;; SOLANGE_CONSOLE) $(build_SOLANGE_CONSOLE) ;; KULPORTAL) $(build_KULPORTAL) ;; WEBSITE) $(build_WEBSITE) ;; \
		GATEWAY) $(build_GATEWAY) ;; SIMULATOR) $(build_SIMULATOR) ;; \
		*) echo "unknown image $$name" >&2; exit 1 ;; \
		esac; \
	done

push: check-images
	@set -a; . ./$(ENV_FILE); set +a; set -e; \
	for name in $(or $(S),$(IMAGES)); do \
		eval "ref=\$${$${name}_IMAGE}:\$${$${name}_TAG}"; echo "== $$ref"; docker push "$$ref"; \
	done

# Images that never go to a registry (localhost/…): built, saved into one
# archive under bundles/, copied to the server (scp), loaded there.
BUNDLED = GATEWAY SIMULATOR
bundle: check-images
	@$(MAKE) --no-print-directory images S="$(or $(S),$(BUNDLED))"
	@set -a; . ./$(ENV_FILE); set +a; set -e; refs=""; name="kulpay-images"; \
	for n in $(or $(S),$(BUNDLED)); do \
		eval "ref=\$${$${n}_IMAGE}:\$${$${n}_TAG}"; \
		case $$ref in localhost/*) ;; *) echo "$$ref is not a localhost/ image; use make push" >&2; exit 1 ;; esac; \
		refs="$$refs $$ref"; name="$$name-$$(echo $$n | tr A-Z a-z)-$$(echo $$ref | sed 's/.*://')"; \
	done; \
	mkdir -p bundles; docker save $$refs | gzip > "bundles/$$name.tar.gz"; \
	(cd bundles && shasum -a 256 "$$name.tar.gz" > "$$name.tar.gz.sha256"); \
	echo "bundles/$$name.tar.gz (and .sha256): scp both to the server's deploy/, then make load FILE=$$name.tar.gz"

load:
	@[ -n "$(FILE)" ] || { echo "usage: make load FILE=kulpay-images-….tar.gz" >&2; exit 2; }
	@if [ -f "$(FILE).sha256" ]; then sha256sum -c "$(FILE).sha256"; else echo "warning: no $(FILE).sha256 to check against" >&2; fi
	gunzip -c "$(FILE)" | docker load

# The login theme Keycloak mounts, from intaka's checkout. Commit the result:
# the server has no intaka checkout.
theme:
	@set -a; . ./$(ENV_FILE); set +a; \
	rm -rf theme && mkdir -p theme && cp -R "$$INTAKA_DIR/demo/theme/kulpay" theme/ && \
	echo "theme/kulpay copied from $$INTAKA_DIR/demo/theme (commit it)"

# A license key for KULOFFICE_LICENSE_KEY, signed with kuloffice's private key
# (KULOFFICE_DIR/keys, the pair of keys/kuloffice-license.pub.base64).
license:
	@set -a; . ./$(ENV_FILE); set +a; \
	$(MAKE) --no-print-directory -C "$$KULOFFICE_DIR" generate-license >/dev/null && cat "$$KULOFFICE_DIR/keys/license.key"; echo

# ── run (server) ──────────────────────────────────────────────────────────────

start: check-images
	$(COMPOSE) up -d

start-portal: check-images
	@set -a; . ./$(ENV_FILE); set +a; [ -n "$${KULPORTAL_TAG:-}" ] || { echo "KULPORTAL_TAG is empty in $(ENV_FILE)" >&2; exit 1; }
	$(COMPOSE) --profile portal up -d

start-website: check-images
	@set -a; . ./$(ENV_FILE); set +a; [ -n "$${WEBSITE_TAG:-}" ] || { echo "WEBSITE_TAG is empty in $(ENV_FILE)" >&2; exit 1; }
	$(COMPOSE) --profile website up -d website

stop:
	$(COMPOSE) --profile portal --profile website down

# Recreates: a plain restart keeps a container's old environment.
restart:
	$(COMPOSE) up -d --force-recreate $(S)

# Follows by default; F=0 prints and exits (for piping into grep), N lines
# (default 200), SINCE e.g. 15m.
F ?= 1
N ?= 200
SINCE ?=
logs:
	$(COMPOSE) --profile portal --profile website logs $(if $(filter 1,$(F)),-f) --tail=$(N) $(if $(SINCE),--since $(SINCE)) $(S)

ps:
	$(COMPOSE) --profile portal --profile website ps -a

update: check-images
	$(COMPOSE) pull --ignore-pull-failures
	$(COMPOSE) up -d

# Destroys every database: Keycloak's users and passkeys, kuloffice's accounts,
# Solange's codes, and the files in MinIO.
clean:
	@printf 'This deletes every database and every stored file. Type DESTROY to continue: '; \
	read answer; [ "$$answer" = "DESTROY" ] || { echo "aborted"; exit 1; }
	$(COMPOSE) --profile portal --profile tools down -v

# Development/installation reset for the financial core. This is intentionally
# whole-database replacement: no partial ledger cleanup or additive repair.
reset-blnk:
	@ENV_FILE="$(ENV_FILE)" YES="$(YES)" sh scripts/reset-blnk.sh

# ── provisioning (server) ─────────────────────────────────────────────────────

init:
	$(COMPOSE) --profile tools run --rm tools /tools/init.sh

# The account webhook (incoming transfers) and the platform event sink
# (payment acceptance) share KulOffice's signed-event intake but have separate
# secrets. Safe to repeat; secrets are rotated only when .env lost its copy.
# The generated values bin/kulpay keeps in .env (Gateway keys and secrets,
# KulOffice's admin password, seal key and wake-up secrets), made if missing.
secrets:
	@$(KULPAY) secrets

# A merchant's bindings on the Gateway, from its Payment Acceptance
# application in KulOffice: APP=pacapp_…. Always KulPay balance (test
# applications in test mode, live ones in live mode); for a live application
# also M-Pesa at the PSP simulator (dev servers only). Safe to repeat: it
# updates the bindings.
merchant-bindings:
	@[ -n "$(APP)" ] || { echo "usage: make merchant-bindings APP=pacapp_…" >&2; exit 1; }
	@ENV_FILE=$(ENV_FILE) COMPOSE="docker compose --env-file $(ENV_FILE)" sh scripts/merchant-bindings.sh "$(APP)"

# KulPay balance at the Gateway's hosted checkout for KulPay's own purchases
# (bills paid on their Gateway invoice link, recharges): one live binding on
# the platform account (GATEWAY_ACCOUNT_ID), destination "platform". KulOffice
# moves the money into its external funds balance. Safe to repeat.
platform-wallet:
	$(COMPOSE) --profile tools run --rm --entrypoint python3 -e BINDING_MODE=platform tools /tools/merchant_bindings.py

gateway-kuloffice:
	@ENV_FILE=$(ENV_FILE) COMPOSE="docker compose --env-file $(ENV_FILE)" sh scripts/gateway-kuloffice.sh

# Partner cash deposits that credit KulPay accounts (owner, 2026-10-20; dev
# only): the lookup secrets, the gateway with its matrix (live cash deposits,
# gateway/launch_matrix.json), KulOffice's account recording deposits for its
# references as incoming transfers, and KulOffice taking them. The PSP side
# (capability row, live key, statement profile) is the partner's, in the
# Gateway portal and dashboard.
cash-deposits:
	@bin/kulpay secrets
	@if grep -q '^KULOFFICE_INCOMING_TRANSFERS_ENABLED=' $(ENV_FILE); then \
		sed -i.bak 's/^KULOFFICE_INCOMING_TRANSFERS_ENABLED=.*/KULOFFICE_INCOMING_TRANSFERS_ENABLED=true/' $(ENV_FILE) && rm -f $(ENV_FILE).bak; \
	else echo 'KULOFFICE_INCOMING_TRANSFERS_ENABLED=true' >> $(ENV_FILE); fi
	$(COMPOSE) up -d --wait --force-recreate gateway
	@GATEWAY_CASH_IN_INCOMING=1 ENV_FILE=$(ENV_FILE) COMPOSE="docker compose --env-file $(ENV_FILE)" sh scripts/gateway-kuloffice.sh

# Billers approved in the back office are provisioned at the Gateway as
# LSPs (KO-1): the partners key is issued on KulOffice's account, KulOffice's
# webhook takes the billers' events, and provisioning is switched on. It
# needs incoming transfers on (make cash-deposits, or the setting).
gateway-billers:
	@grep -q '^KULOFFICE_INCOMING_TRANSFERS_ENABLED=true' $(ENV_FILE) || { echo "turn incoming transfers on first (KULOFFICE_INCOMING_TRANSFERS_ENABLED=true): the billers' status comes on its webhook" >&2; exit 1; }
	@GATEWAY_BILLER_PROVISIONING=1 ENV_FILE=$(ENV_FILE) COMPOSE="docker compose --env-file $(ENV_FILE)" sh scripts/gateway-kuloffice.sh

# The PSP simulator as a partner bank, brought in by the same provisioner as
# a real bank's pilot (../bank-deploy/provisioning/psp_provision.py with
# simulator-bank.example.yaml): application, KYB, terms, capabilities, its
# webhook endpoint, certification (the simulator answers, statement included)
# and the pilot; its trust account's camt.053 profile and safeguarding
# account; the simulator receives its keys, webhook secrets and profiles. Safe to
# repeat: it resumes. SIMBANK=plan checks without changing anything;
# SIMBANK=rollback suspends it. State, secrets and the readiness report:
# simulator-bank-output/ (root-only).
SIMBANK ?= apply
simulator-bank:
	@mkdir -p simulator-bank-output && chmod 700 simulator-bank-output
	$(COMPOSE) --profile tools run --rm --no-deps -u 0 \
		-v "$(CURDIR)/../bank-deploy/provisioning:/psp:ro" -v "$(CURDIR)/simulator-bank-output:/output" \
		-e PSP_CONFIG=/psp/simulator-bank.example.yaml -e PSP_OUTPUT=/output \
		-e GATEWAY_PUBLIC_INTERNAL_URL=http://gateway:9090 \
		--entrypoint sh tools -c 'python3 -c "import yaml" 2>/dev/null || python3 -m pip install --quiet --disable-pip-version-check --target /tmp/py pyyaml; PYTHONPATH=/tmp/py exec python3 /psp/psp_provision.py $(SIMBANK)'

# ROLE=ADMIN: an admin, holding every permission in kuloffice's catalogue.
ROLE ?= Revisores
SOLANGE ?=
GATEWAY ?=
operator:
	@[ -n "$(EMAIL)" ] || { echo "usage: make operator EMAIL=… FIRST=… LAST=… [ROLE=Revisores|ADMIN] [SOLANGE=viewer] [GATEWAY=1]" >&2; exit 1; }
	$(COMPOSE) --profile tools run --rm -e STAFF_EMAIL="$(EMAIL)" -e STAFF_FIRST_NAME="$(FIRST)" -e STAFF_LAST_NAME="$(LAST)" \
		-e KULOFFICE_ROLE="$(ROLE)" -e SOLANGE_ROLES="$(SOLANGE)" -e GATEWAY_OPERATOR="$(GATEWAY)" tools /tools/operator.sh

# The Gateway operator dashboard's sign-in (workforce realm): its secret into
# .env, its Keycloak client, then the gateway recreated to read them. Grant
# staff its role with make operator … GATEWAY=1.
gateway-signin:
	@bin/kulpay secrets
	$(COMPOSE) --profile tools run --rm tools -c 'KC_BOOTSTRAP_ADMIN_USERNAME="$${KC_ADMIN_USER:-admin}" KC_BOOTSTRAP_ADMIN_PASSWORD="$$KC_ADMIN_PASSWORD" python3 /tools/gateway_admin_client.py'
	$(COMPOSE) up -d --force-recreate gateway-config gateway

# KulPay's app in Solange, kuloffice's key and the webhook to kuloffice, each
# step only if missing; the secrets go straight into .env, then kuloffice is
# recreated to read them.
solange-kulpay:
	@ENV_FILE=$(ENV_FILE) COMPOSE="$(COMPOSE)" sh scripts/solange-kulpay.sh

# ── releases (server) ─────────────────────────────────────────────────────────
#
# bin/kulpay: what CI runs over SSH, for people. U is a unit (lib/units.sh):
# keycloak, kuloffice, web, fileserver, solange, kulportal.

KULPAY = ENV_FILE=$(ENV_FILE) bin/kulpay --actor "$${SUDO_USER:-$$USER}"

deploy:
	@[ -n "$(U)" ] && [ -n "$(T)" ] || { echo "usage: make deploy U=<unit> T=<tag>" >&2; exit 1; }
	@$(KULPAY) deploy $(U) $(T)

rollback:
	@[ -n "$(U)" ] || { echo "usage: make rollback U=<unit> [STEPS=1 | TO=<tag>] [YES=1]" >&2; exit 1; }
	@$(KULPAY) rollback $(U) $(if $(TO),--to $(TO),--steps $(or $(STEPS),1)) $(if $(YES),--yes)

releases:
	@$(KULPAY) releases $(U)

status:
	@$(KULPAY) status

health:
	@$(KULPAY) health $(U)

backup:
	@[ -n "$(DB)" ] || { echo "usage: make backup DB=<kuloffice|keycloak|solange>" >&2; exit 1; }
	@$(KULPAY) backup $(DB)

restore:
	@[ -n "$(DB)" ] && [ -n "$(FILE)" ] || { echo "usage: make restore DB=<database> FILE=<backup> YES=1" >&2; exit 1; }
	@$(KULPAY) restore $(DB) $(FILE) $(if $(YES),--yes)
