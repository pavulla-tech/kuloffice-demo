# The local kuloffice test stack. `make up` is all it takes: it builds every
# image from the sibling checkouts, starts the stack and configures it - realm
# and clients, MinIO buckets, license, identity provider - so it is ready to
# sign in to.
#
# Each of Keycloak, kuloffice and the web app can instead come from Docker Hub
# (a tag, or `release`) or be the deployed one (`server`): KEYCLOAK, KULOFFICE,
# WEB in stack.env, or for one run `make up WEB=build KULOFFICE=server …`, or
# PRESET=web|kuloffice|local. stack/resolve.sh works out the rest.
#
# Settings are in stack.env (created from stack.env.example on first use).

.PHONY: help up plan where down restart rebuild logs ps urls bootstrap realm buckets reviewer review kuloffice sms ussd-test db psql \
        keys license config clean legacy-stop

# Creates stack.env first if it is missing, with its own web session secret.
-include stack.env

STACK_NAME ?= kulstack
KC_PORT ?= 8080
KULOFFICE_PORT ?= 18080
WEB_PORT ?= 3000
PANEL_PORT ?= 8765
SMS_INBOX_PORT ?= 8090
FILESERVER_PORT ?= 8082
MINIO_CONSOLE_PORT ?= 9001
DB_PORT ?= 5432
KULOFFICE_ADMIN_EMAIL ?= admin@kulpay.local
KULOFFICE_ADMIN_PASSWORD ?= localadmin
MINIO_ROOT_USER ?= kulstack
MINIO_ROOT_PASSWORD ?= kulstack-local
REVIEWER_EMAIL ?= reviewer@kulpay.local
REVIEWER_PASSWORD ?= reviewer
INTAKA_DIR ?= ../keycloak-phone-authenticator

# The license signing key pair. The public half is built into the kuloffice
# image; bootstrap signs a license with the private half. Gitignored.
KEYS := .stack/keys

# -f names the file so that the untracked docker-compose.override.yml (the
# older two-project wiring) is never merged in.
# .stack/resolved.env (stack/resolve.sh, on every make up) says what runs here
# and wires it to what doesn't; its COMPOSE_PROFILES picks the services.
RESOLVED := .stack/resolved.env
COMPOSE = LICENSE_PUBLIC_KEY="$$(cat $(KEYS)/public.pem.base64 2>/dev/null)" \
	COMPOSE_PROFILES="$$(sed -n 's/^COMPOSE_PROFILES=//p' $(RESOLVED) 2>/dev/null)" \
	docker compose -p $(STACK_NAME) -f docker-compose.yml --env-file stack.env \
	$$([ -f $(RESOLVED) ] && echo --env-file $(RESOLVED))

# Where each switchable service comes from (see stack.env.example). Passed to
# stack/resolve.sh with the settings it needs.
RESOLVE_VARS = KEYCLOAK PRESET KULOFFICE WEB FILESERVER STACK_NAME STACK_BIND KC_PORT KULOFFICE_PORT KULOFFICE_GRPC_PORT \
	WEB_PORT PANEL_PORT SMS_INBOX_PORT FILESERVER_PORT MINIO_PORT MINIO_CONSOLE_PORT DB_PORT \
	INTAKA_DIR KULOFFICE_DIR WEB_DIR FILESERVER_DIR WORKFORCE_API_SECRET REVIEWER_EMAIL \
	SERVER_KEYCLOAK_URL SERVER_KULOFFICE_URL SERVER_WEB_URL SERVER_REALM SERVER_ADMIN_CLIENT_SECRET \
	SERVER_WORKFORCE_API_SECRET SERVER_LICENSE_KEY SERVER_KC_ADMIN_USER SERVER_KC_ADMIN_PASSWORD \
	SERVER_REVIEWER_EMAIL SOLANGE_URL SOLANGE_API_KEY

# A service name, for the targets that take one: make logs S=kuloffice
S ?=

help:
	@echo "make up              build, start and configure the stack (what stack.env says is local)"
	@echo "make up PRESET=web|kuloffice|local    web: only the web app here; kuloffice: web + kuloffice"
	@echo "                     here, Keycloak on the server; local: everything here"
	@echo "make up WEB=build KULOFFICE=server KEYCLOAK=v0.1.0-alpha03 …   any mix, for one run"
	@echo "                     (build | a Docker Hub tag | release | server)"
	@echo "make plan [X=…]      what make up would run here and use on the server (starts nothing)"
	@echo "make where           what this run uses, and where"
	@echo "make down            stop it (data is kept)"
	@echo "make restart [S=x]   restart everything, or one service"
	@echo "make rebuild [S=x]   rebuild from the checkouts and restart (after a code change)"
	@echo "make logs [S=x]      follow logs"
	@echo "make ps / urls       what is running / where to find it"
	@echo "make bootstrap       re-run license activation and IdP registration"
	@echo "make realm           re-run the Keycloak realm setup"
	@echo "make buckets         re-run the MinIO bucket setup"
	@echo "make reviewer        re-run the demo reviewer's seeding (operator, identity, role)"
	@echo "make review ACCOUNT=acc_... [OUTCOME=approve|reject|request_documents] [MESSAGE=...] [DOCS=TYPE:text;...]"
	@echo "                     decide an account's KYC review as the demo reviewer"
	@echo "make kuloffice       recreate kuloffice with stack.kuloffice.env (MiniAiLive etc.)"
	@echo "make sms             print the dev SMS inbox (OTP codes, kuloffice SMS)"
	@echo "make ussd-test       drive intaka's USSD channel end to end against this stack's Keycloak"
	@echo "make psql            psql into kuloffice's database"
	@echo "make license         print a fresh license key signed with the stack's key"
	@echo "make clean           remove containers and volumes (keys and stack.env stay)"
	@echo "make legacy-stop     stop the older demo + kuloffice-demo containers holding the same ports"

stack.env: stack.env.example
	@if [ -f $@ ]; then \
		echo "stack.env is older than stack.env.example: compare them for new settings." >&2; touch $@; \
	else \
		awk -v s="$$(openssl rand -hex 32)" \
			'/^KULPAY_SESSION_SECRET=/ { print "KULPAY_SESSION_SECRET=" s; next } { print }' $< > $@; \
		echo "Created stack.env"; \
	fi

keys: $(KEYS)/private.pem

$(KEYS)/private.pem:
	@mkdir -p $(KEYS)
	@openssl genrsa -out $@ 4096 2>/dev/null
	@chmod 600 $@
	@openssl rsa -in $@ -pubout -out $(KEYS)/public.pem 2>/dev/null
	@openssl base64 -A -in $(KEYS)/public.pem > $(KEYS)/public.pem.base64
	@echo "Generated the license key pair in $(KEYS)"

# What make up would run here and use on the server, without starting it.
plan: stack.env
	@$(foreach v,$(RESOLVE_VARS),$(if $(value $(v)),$(v)="$($(v))") )sh stack/resolve.sh

up: stack.env keys plan
	@set -a; . ./$(RESOLVED); set +a; \
		if [ -n "$$STACK_STOP" ]; then $(COMPOSE) --profile '*' stop $$STACK_STOP 2>/dev/null; \
			$(COMPOSE) --profile '*' rm -f $$STACK_STOP >/dev/null 2>&1; fi; \
		if [ -n "$$STACK_BUILD" ]; then $(COMPOSE) --profile '*' build $$STACK_BUILD; fi
	$(COMPOSE) up -d --no-build
	@set -a; . ./$(RESOLVED); set +a; \
		wait_for() { id=$$($(COMPOSE) ps -aq $$1); [ -n "$$id" ] || return 0; \
			until [ "$$(docker inspect -f '{{.State.Status}}' $$id)" = "exited" ]; do sleep 1; done; \
			$(COMPOSE) logs --no-log-prefix $$1; \
			code=$$(docker inspect -f '{{.State.ExitCode}}' $$id); \
			if [ "$$code" != "0" ]; then echo "$$1 failed (exit $$code)" >&2; exit 1; fi; }; \
		if [ "$$STACK_KULOFFICE_LOCAL" = yes ]; then echo "Configuring kuloffice…"; wait_for bootstrap; fi; \
		if [ "$$STACK_SEED" = yes ]; then wait_for reviewer-seed; fi
	@$(MAKE) --no-print-directory where

# What the last make up runs here and what it uses on the server.
where:
	@[ -f .stack/where.txt ] || { echo "nothing yet: make up" >&2; exit 1; }
	@echo ""
	@cat .stack/where.txt
	@echo "token     http://localhost:$(PANEL_PORT)   panel; sign in to whichever Keycloak above"
	@set -a; . ./$(RESOLVED); set +a; case ",$$COMPOSE_PROFILES," in *,base,*) \
		echo "sms       http://localhost:$(SMS_INBOX_PORT)/api/dev/inbox   codes from this laptop's Keycloak and kuloffice (make sms)"; \
		echo "postgres  localhost:$(DB_PORT)   kuloffice / kuloffice (make psql)";; esac
	@set -a; . ./$(RESOLVED); set +a; case ",$$COMPOSE_PROFILES," in *,keycloak,*) \
		echo "admin     http://localhost:$(KC_PORT)/auth/admin   admin / admin   realm: demo";; esac
	@set -a; . ./$(RESOLVED); set +a; case ",$$COMPOSE_PROFILES," in *,seed,*) \
		echo "reviewer  $$SEED_EMAIL (token panel, Reviewer card)";; esac

down:
	$(COMPOSE) --profile '*' down

restart:
	$(COMPOSE) restart $(S)

# Only what is built here; a tag or the server has nothing to rebuild.
rebuild: stack.env keys
	@set -a; . ./$(RESOLVED); set +a; for s in $(or $(S),$$STACK_BUILD); do \
		case " $$STACK_BUILD " in *" $$s "*) ;; *) case $$s in keycloak|kuloffice|web|fileserver) \
			echo "$$s isn't built here this run (make where)" >&2; exit 1;; esac;; esac; done
	$(COMPOSE) up -d --build $(S)

logs:
	$(COMPOSE) logs -f $(S)

ps:
	$(COMPOSE) ps -a

# The older name for `make where`.
urls: where

bootstrap:
	$(COMPOSE) up --no-deps --force-recreate bootstrap

realm:
	$(COMPOSE) up --no-deps --force-recreate realm-setup

buckets:
	$(COMPOSE) up --no-deps --force-recreate minio-init

reviewer:
	$(COMPOSE) up --no-deps --force-recreate reviewer-seed

# As the demo reviewer, through the review-case API (see stack/review.py).
review:
	@PANEL_URL=http://localhost:$(PANEL_PORT) KULOFFICE_URL=http://localhost:$(KULOFFICE_PORT) \
		WORKFORCE_ISSUER=http://localhost:$(KC_PORT)/auth/realms/workforce \
		REVIEWER_EMAIL="$(REVIEWER_EMAIL)" REVIEWER_PASSWORD="$(REVIEWER_PASSWORD)" \
		ACCOUNT="$(ACCOUNT)" OUTCOME="$(OUTCOME)" REASON="$(REASON)" MESSAGE="$(MESSAGE)" DOCS="$(DOCS)" \
		python3 stack/review.py

# A plain restart keeps the old environment; settings need a new container.
kuloffice:
	$(COMPOSE) up -d --no-deps --force-recreate kuloffice

sms:
	@curl -fsS http://localhost:$(SMS_INBOX_PORT)/api/dev/inbox | python3 -m json.tool

# intaka's demo/tools/ussd_flow_test.py: register, sign in, wrong PINs, the
# shared lockout. In the stack's network namespace, because one check logs in
# to the master realm, which refuses plain-HTTP admin logins from elsewhere.
ussd-test:
	@docker run --rm --network container:$$($(COMPOSE) ps -q net) \
		-v "$(abspath $(INTAKA_DIR))/demo/tools:/tools:ro" \
		-e KEYCLOAK_URL=http://localhost:$(KC_PORT)/auth python:3.12-alpine python3 /tools/ussd_flow_test.py

# The older Makefile's name for it.
db: psql

psql:
	$(COMPOSE) exec db psql -U kuloffice kuloffice

license: keys
	@$(COMPOSE) run --rm --no-deps --entrypoint kuloffice-license -v "$(CURDIR)/$(KEYS):/keys:ro" --user root \
		bootstrap generate --issuer=pavulla.com --priv-key=/keys/private.pem --issued-to=kuloffice-demo --valid-days=365
	@echo ""

config: stack.env
	$(COMPOSE) config

clean:
	$(COMPOSE) --profile '*' down -v --remove-orphans

# The setup this replaces ran as two compose projects - intaka's demo
# (phoneauth-*) and this repository's (kuloffice, kuloffice-db) - on the same
# ports. Stops them; their containers and data stay, for `docker start`.
legacy-stop:
	-docker compose -p demo stop
	-docker compose -p kuloffice-demo stop
