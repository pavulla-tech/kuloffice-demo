# The local kuloffice test stack. `make up` is all it takes: it builds every
# image from the sibling checkouts, starts the stack and configures it - realm
# and clients, MinIO buckets, license, identity provider - so it is ready to
# sign in to.
#
# Settings are in stack.env (created from stack.env.example on first use).

.PHONY: help up down restart rebuild logs ps urls bootstrap realm buckets reviewer review kuloffice sms ussd-test psql \
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
COMPOSE = LICENSE_PUBLIC_KEY="$$(cat $(KEYS)/public.pem.base64 2>/dev/null)" \
	docker compose -p $(STACK_NAME) -f docker-compose.yml --env-file stack.env

# A service name, for the targets that take one: make logs S=kuloffice
S ?=

help:
	@echo "make up              build, start and configure the whole stack"
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

up: stack.env keys
	$(COMPOSE) up -d --build
	@echo "Configuring kuloffice…"
	@id=$$($(COMPOSE) ps -aq bootstrap); \
		until [ "$$(docker inspect -f '{{.State.Status}}' $$id)" = "exited" ]; do sleep 1; done; \
		$(COMPOSE) logs --no-log-prefix bootstrap; \
		code=$$(docker inspect -f '{{.State.ExitCode}}' $$id); \
		if [ "$$code" != "0" ]; then echo "bootstrap failed (exit $$code)" >&2; exit 1; fi
	@id=$$($(COMPOSE) ps -aq reviewer-seed); \
		until [ "$$(docker inspect -f '{{.State.Status}}' $$id)" = "exited" ]; do sleep 1; done; \
		$(COMPOSE) logs --no-log-prefix reviewer-seed; \
		code=$$(docker inspect -f '{{.State.ExitCode}}' $$id); \
		if [ "$$code" != "0" ]; then echo "reviewer seeding failed (exit $$code)" >&2; exit 1; fi
	@$(MAKE) --no-print-directory urls

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart $(S)

rebuild: stack.env keys
	$(COMPOSE) up -d --build $(S)

logs:
	$(COMPOSE) logs -f $(S)

ps:
	$(COMPOSE) ps -a

urls:
	@echo ""
	@echo "Web app          http://localhost:$(WEB_PORT)"
	@echo "Token panel      http://localhost:$(PANEL_PORT)   reviewer: $(REVIEWER_EMAIL) / $(REVIEWER_PASSWORD) (Reviewer card)"
	@echo "kuloffice API    http://localhost:$(KULOFFICE_PORT)   admin: $(KULOFFICE_ADMIN_EMAIL) / $(KULOFFICE_ADMIN_PASSWORD) (Basic)"
	@echo "Keycloak         http://localhost:$(KC_PORT)/auth/admin   admin / admin   realm: demo"
	@echo "Demo backend     http://localhost:$(SMS_INBOX_PORT)   intaka's demo page; SMS inbox at /api/dev/inbox (make sms)"
	@echo "MinIO console    http://localhost:$(MINIO_CONSOLE_PORT)   $(MINIO_ROOT_USER) / $(MINIO_ROOT_PASSWORD)"
	@echo "File server      http://localhost:$(FILESERVER_PORT)"
	@echo "Postgres         localhost:$(DB_PORT)   kuloffice / kuloffice (make psql)"

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

psql:
	$(COMPOSE) exec db psql -U kuloffice kuloffice

license: keys
	@$(COMPOSE) run --rm --no-deps --entrypoint kuloffice-license -v "$(CURDIR)/$(KEYS):/keys:ro" --user root \
		bootstrap generate --issuer=pavulla.com --priv-key=/keys/private.pem --issued-to=kuloffice-demo --valid-days=365
	@echo ""

config: stack.env
	$(COMPOSE) config

clean:
	$(COMPOSE) down -v --remove-orphans

# The setup this replaces ran as two compose projects - intaka's demo
# (phoneauth-*) and this repository's (kuloffice, kuloffice-db) - on the same
# ports. Stops them; their containers and data stay, for `docker start`.
legacy-stop:
	-docker compose -p demo stop
	-docker compose -p kuloffice-demo stop
