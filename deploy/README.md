# KulPay deployment

The whole of KulPay on one server, in one compose stack:

| Service | Public URL (Apache) | Host port | What it is |
|---|---|---|---|
| `keycloak` | https://auth.kulpay.pavulla.com | 9180 | Keycloak with intaka's phone authenticator; the customer realm (`kulpay`) and the staff realm (`workforce`) |
| `kuloffice` | https://core.kulpay.pavulla.com | 9280 | The API the mobile app, the web app and the token panel call |
| `web` | https://app.kulpay.pavulla.com | 9380 | The KulPay web app |
| `token-panel` | https://panel.kulpay.pavulla.com (password) | 9480 | Signs numbers and staff in and keeps their tokens fresh |
| `solange` | https://qr.kulpay.pavulla.com | 9580 | Solange: QR codes, scans, webhooks |
| `solange-console` | https://console.qr.kulpay.pavulla.com | 9680 | Solange's staff console |
| `kulportal` | https://portal.kulpay.pavulla.com | 9780 | Off until ready (`make start-portal`) |
| `blnk-server`, `blnk-worker` | — | — | Pinned self-hosted BLNK API and its queue processor; internal only |
| `gateway` | — | — | KulPay's own payments gateway (katembe-payments), live mode; KulOffice uses its public root for top-ups and its management `/v1` API for transfers, supply, Payment Acceptance and reconciliation. Internal only |
| `simulator` | https://sim.kulpay.pavulla.com (password) | 9880 | Development only: the PSP simulator the gateway's live M-Pesa, e-Mola and card bindings point at, and its customer page |
| `db` | — | — | Postgres 17: one isolated database and role each for kuloffice, Keycloak, Solange, BLNK, the gateway |
| `blnk-redis`, `blnk-typesense` | — | — | BLNK's durable queue and rebuildable search projection; internal only |
| `minio`, `fileserver` | — | — | MinIO behind KulPay's own boquisso file server, where kuloffice keeps KYC files |
| `tools` | — | — | Provisioning, run on demand (`make init`, `make operator`) |

Every port is bound to `127.0.0.1`; Apache on the host terminates TLS and
proxies each hostname to its port (`apache/`). The server never builds: images
are built on a laptop and pushed to Docker Hub, the server pulls them.

## On the laptop: images

Sibling checkouts, as `.env`'s `*_DIR` say (`kuloffice-demo`, `kuloffice`,
`keycloak-phone-authenticator`, `kulpay-web`, `boquisso-fileserver`, and
`../solange/solange`), each on the branch being deployed. Then:

```bash
cd kuloffice-demo/deploy
make setup                   # .env from .env.example; set the *_TAG values
docker login                 # an account that can push to developerspavs/*
make images                  # every image, for linux/amd64; or S=WEB for one
make push
make license                 # prints a KULOFFICE_LICENSE_KEY for the server's .env
```

- kuloffice's image links the license public key from
  `keys/kuloffice-license.pub.base64` here (CI uses it too); `make license`
  signs with its private key, `KULOFFICE_DIR/keys/private.pem.base64`. Keep
  that pair: a license only verifies against its own key.
- Solange is built from `cmd/solange` (the new core). Its own `Dockerfile`
  builds the old app; this one does not use it.
- `make theme` refreshes `theme/kulpay` (the login look, from intaka's
  `demo/theme`). Commit it: the server only has this repository.
- Give every release new tags (e.g. `2026.10.02-1`). Reusing a tag makes
  `make update` a no-op on a server that already pulled it.

## On the server: first deployment

Docker with Compose, Apache, make, git. No toolchains.

**1. Settings.**

```bash
git clone git@github.com:pavulla-tech/kuloffice-demo.git && cd kuloffice-demo/deploy
make setup                   # .env and kuloffice.env (both gitignored, 600)
$EDITOR .env                 # every empty value; the comments say how to generate secrets
$EDITOR kuloffice.env        # MiniAiLive, NUIB API, idfort, SMS templates
make config                  # fails on anything still missing
```

The original service database passwords are used once, when Postgres first
starts on an empty volume. BLNK is also prepared by an idempotent init service,
so it can be added to an existing stack and its role password follows `.env`.
The gateway's database is prepared the same way (`gateway-db-init`).

**2. Start.**

```bash
make start
make ps                      # keycloak and BLNK healthy; one-shot init/migrations exited 0
```

KulOffice waits for BLNK, then discovers or creates the environment-scoped MZN
topology: customer-product and connector-collection ledgers, and General Ledger
external-funds and product-fees balances. It verifies stable ownership metadata
on every start and never stores provider-generated IDs in `.env`. BLNK and its
worker use the same pinned `BLNK_TAG`; no BLNK port is published on the host.

For a deliberate development reinstall, `make reset-blnk YES=DESTROY` stops
both executors, saves a compressed database dump, replaces the complete BLNK
database plus its Redis/Typesense state, reapplies the pinned schema, and then
starts KulOffice so the topology bootstrap runs. It does not partially delete
ledger rows and does not touch customer authentication, KulOffice, Solange, or
MinIO data. The printed backup can be restored with `make restore DB=blnk ...`.

**Provider integration on a development server.** kuloffice uses the stack's
own gateway, whose live M-Pesa, e-Mola and card bindings point at the PSP
simulator: `gateway-bind` (re)writes them and their callback destinations on
every start, and kuloffice waits for it. The simulator workbench covers charges,
payouts, name lookup, provider float, status recovery, card capture/refund,
signed callbacks and failure scenarios. With a QA partner key and statement
profile in the `SIMULATOR_GATEWAY_*` settings it also calls the gateway as a
partner bank for incoming transfers, cash deposits, statements and settlement
reports. Bill suppliers remain excluded until their gateway integration is
updated. On this server simulated provider operations are live-mode
transactions. The simulator and `gateway-bind` must never run beside real
provider credentials; see `kuloffice/docs/security-plan.md` for the controls
planned before production.

The gateway and simulator images never go to a registry (`localhost/…`
names cannot be pulled). On the laptop, `make bundle` builds both at the tags
in `.env` into `bundles/kulpay-images-….tar.gz` with its `.sha256`; copy both
to the server's `deploy/` and run `make load FILE=kulpay-images-….tar.gz`
there before setting `GATEWAY_TAG` / `SIMULATOR_TAG`. A deploy refuses a
`localhost/` tag that is not loaded.

### PSP onboarding and the simulator's Gateway connection

PSPs apply at `GATEWAY_PUBLIC_URL/onboarding` (on the development server,
`https://gateway.kulpay.pavulla.com/onboarding`). The Gateway keeps its own
onboarding lifecycle, KYB review, technical setup, certification, pilot and
go-live; this is not a KulOffice or simulator form.

Application confirmations and partner-portal sign-in links use the Gateway's
notification outbox. Configure `KULPAY_SMTP_ADDR`, `KULPAY_SMTP_FROM`,
`KULPAY_SMTP_USERNAME` and `KULPAY_SMTP_PASSWORD` in the server's ignored
`deploy/.env`, then recreate the Gateway with `make restart S=gateway`. The
relay takes PLAIN auth over STARTTLS (normally port 587) or implicit TLS on
port 465 (gateway v0.1.1-alpha07 on). Verify with
`docker compose --env-file .env logs gateway` that there is no
`no mail relay configured` warning and no SMTP delivery error.

The simulator has two distinct Gateway relationships:

- its provider endpoints are already bound by `gateway-bind` for KulPay's own
  payments; the successful `bound mpesa/emola/card` output confirms that link;
- its Partner Bank workbench needs a PSP's own key. Once the enrolled PSP
  reaches technical setup, reveal its sandbox key once, save it as
  `SIMULATOR_GATEWAY_PARTNER_KEY` with `SIMULATOR_GATEWAY_MODE=test`, and
  recreate the simulator with `make restart S=simulator`. Until then, the
  workbench's “Gateway not configured” state is expected and does not mean the
  provider bindings are broken.

### Partner cash deposits (development)

`make cash-deposits` makes a partner's cash deposit credit the KulPay account
it was taken for: it generates the lookup secrets if missing, recreates the
gateway with `gateway/launch_matrix.json` (the embedded matrix plus live cash
deposits, owner 2026-10-20), turns on `cash_in_incoming` for KulOffice's
gateway account, provisions KulOffice's event endpoint and sets
`KULOFFICE_INCOMING_TRANSFERS_ENABLED=true`. KulOffice credits live deposits
only (test-mode ones are ignored), and its test-mode lookup answers only the
sandbox references `841000001` (found) and `841000410` (closed).

The partner side is the PSP's: a capability matrix with a `NAME_LOOKUP` row for
`cash_deposit` (approved in the dashboard), a live key (issued at pilot) set as
`SIMULATOR_GATEWAY_PARTNER_KEY` with `SIMULATOR_GATEWAY_MODE=live`, and a
statement profile for the receiving account (`SIMULATOR_STATEMENT_PROFILE_ID`),
since a deposit is credited only when the statement shows it.

**3. Apache.** For each file in `apache/`: get its certificate (`certbot
certonly --apache -d <host>`), copy it to `/etc/apache2/sites-available/`,
`a2ensite`, then `systemctl reload apache2`. Once:

```bash
a2enmod proxy proxy_http headers ssl auth_basic authn_file
htpasswd -c /etc/apache2/kulpay-panel.htpasswd <user>    # the token panel's password
htpasswd -c /etc/apache2/kulpay-simulator.htpasswd <user>  # the PSP simulator's (development only)
```

Keycloak builds `http://` URLs and bounces the browser between schemes unless
the vhost sends `X-Forwarded-Proto: https` (the snippets do). Solange believes
forwarded addresses only from the stack's gateway (`STACK_GATEWAY`).

**4. Provision.**

```bash
make init
```

Idempotent, so safe to run again after any change:
- **Customer realm (`kulpay`):** the phone flows, and the web, passkey, mobile,
  token panel and USSD clients, with the extension's own sign-in limits
  (3 codes a number an hour).
- **Staff realm (`workforce`):** kuloffice's client, the panel's, and
  `solange-console` with its roles.
- **kuloffice:** the license and both identity providers, under the public
  issuers.

An existing realm is left alone. Rebuilding it would rotate its signing keys
and invalidate every token. `FORCE_RESET=true make init` rebuilds it on
purpose.

**5. Staff.**

```bash
make operator EMAIL=ana@pavulla.com FIRST=Ana LAST=Macuacua                 # a KYC reviewer
make operator EMAIL=rui@pavulla.com FIRST=Rui LAST=Lopes SOLANGE=developer   # also in Solange
make operator EMAIL=eva@pavulla.com FIRST=Eva LAST=Sitoe ROLE= SOLANGE=viewer # Solange only
make operator EMAIL=ze@pavulla.com FIRST=Zé LAST=Tembe ROLE=ADMIN SOLANGE=admin  # an admin, everywhere
make operator EMAIL=lia@pavulla.com FIRST=Lia LAST=Cossa ROLE= GATEWAY=1        # the Gateway dashboard only
```

- **`GATEWAY=1`:** the Gateway operator dashboard (`https://mgnt.kulpay.pavulla.com/admin/`).
  Turn its sign-in on once: `GATEWAY_OIDC_ENABLED=true` in `.env`, then
  `make gateway-signin` (its client in the workforce realm, the generated secrets, the
  gateway recreated). Each operator signs in as themselves, so the Gateway's four-eyes
  approvals need two people with the role. The development admin gets it on every deploy.

- **The account:** a workforce account with a temporary password (printed
  once, changed at the first sign-in).
- **`ROLE`** (default `Revisores`, KYC review permissions): a kuloffice
  operator bound to the account, holding that role and the Conta Pagamento
  back-office role (`Produtos (local)`).
- **`ROLE=ADMIN`:** an admin instead. The operator holds `Administradores`:
  every permission in kuloffice's catalogue, read from
  `GET /v1/operator-permissions` and re-applied on every run, so permissions
  added later reach admins once `make operator … ROLE=ADMIN` runs again.
  Creating or editing roles stays with the env-admin; an admin can grant only
  roles whose permissions they hold, never to themselves.
- **`SOLANGE`:** console roles, any of `viewer`, `developer`, `admin`.

**6. QR codes** (kuloffice through Solange):

```bash
make solange-kulpay
```

Creates KulPay's app in Solange (`kulpay-app`; printed codes are
`https://qr.kulpay.pavulla.com/k/<code>`), kuloffice's key and the webhook to
`https://core.kulpay.pavulla.com/v1/integrations/solange/events`. Each step is
skipped when it's already done. The key and the webhook secret are written into
`.env` without being printed, and kuloffice is recreated with QR codes on.

Run it again any time; to issue a new key, clear `KULOFFICE_SOLANGE_API_KEY`
first. Solange posts webhooks to `core.` over HTTPS through the host's Apache
(the `solange` service resolves that name to the stack's gateway). Check the
path with:

```bash
docker compose exec solange wget -S -O /dev/null https://core.kulpay.pavulla.com/ 2>&1 | grep HTTP/   # any HTTP status: the path works
```

For the KulPay app to open scanned codes itself, put the mobile team's
`assetlinks.json` and `apple-app-site-association` in `/srv/kulpay/well-known/`
(see `apache/solange.conf`).

## Moving over from the old stacks

The old Keycloak kit (`keycloak/demo/deploy`) and the old kuloffice compose use
ports 8180/8280/8380. This stack uses 9180 and up, so both can run at once:

1. Start this stack and `make init` (above). Nothing public points at it yet.
2. Switch the vhosts for `auth.` and `core.` to the new ports, add the new
   hostnames, `systemctl reload apache2`.
3. Stop the old stacks: `make stop` in `keycloak/demo/deploy`, and
   `docker compose down` in the old kuloffice folder. Their volumes stay until
   you remove them, in case you need to look back.

This is a fresh start: nobody's accounts carry over. Users sign up again, and
the mobile apps' saved sessions and device keys stop working once `auth.`
points here.

## Releases (CI)

Each service repository releases itself: push a tag, and GitHub Actions tests,
builds, pushes to Docker Hub and deploys on this server. The full guide,
including every secret the repositories need: [../CICD.md](../CICD.md).

```bash
git tag v0.1.0-alpha03 && git push origin v0.1.0-alpha03
```

| Repository | Unit | Images | Its data |
|---|---|---|---|
| intaka | `keycloak` | keycloak (with the login theme), token-panel, tools | Keycloak's database |
| kuloffice | `kuloffice` | kuloffice | kuloffice's database and its MinIO buckets |
| kulpay-webapp | `web` | web | none |
| boquisso-fileserver | `fileserver` | fileserver | none |
| solange | `solange` | solange, solange-console | Solange's database |
| kulportal | `kulportal` | kulportal | none (no workflow yet) |
| katembe-payments | `gateway` | gateway (bundle, not Docker Hub) | the gateway's database (a reset wipes kuloffice too: its top-ups hold the gateway's ids) |
| kulpay-psp-simulator | `simulator` | simulator (bundle, not Docker Hub) | its prompts and balances (a volume) |

Each repository's `.github/workflows/release.yml` runs its tests, then this
repository's reusable `service.yml`, which builds with the same recipes as
`make images` (`ci/build.sh`) and runs `deploy <unit> <tag>` on the server.

**Tags.** `vMAJOR.MINOR.PATCH-alphaNN`; the workflow file must be in the
tagged commit.

- **A new alpha** (`v0.1.0-alpha02` → `alpha03`) updates in place: the
  unit's database is backed up, the tag switched, the unit health-checked
  (running, healthy, not restarting, and its own endpoint where it has one).
  If it fails, it goes back to the previous tag (and, if that fails too on
  the migrated data, to the backup), and the run turns red: GitHub emails
  whoever pushed the tag.
- **A new patch or minor** (`v0.1.0-*` → `v0.1.1-*`) resets the unit: its
  data is saved, wiped and started fresh, along with the units whose data
  points into it:
  - Keycloak → kuloffice too (its accounts hold Keycloak's user ids), its
    files, then `init`. Staff accounts are gone: `make operator` again.
  - Solange → kuloffice's QR records, then `solange-kulpay` (a new key).
  - kuloffice → its files, then `init`.

  If the reset fails, everything it wiped is put back.
- **Nothing rolls back below the current minor:** a `v0.2.0` ends `v0.1`'s
  history.

**Rollback.** kuloffice-demo's **Rollback** workflow (Actions → Rollback →
Run): a unit, then "steps" back or an exact tag ("to"). Within a version only
the image changes. Across a reset, the data that reset saved is restored for
every unit it wiped, and what they stored since is lost: the run stops and
says so unless "confirm" is ticked. The **Server** workflow shows `releases`
(the tags a rollback can go to), `status` and `health`.

**On the server** the same tool, `bin/kulpay`:

```bash
make status                          # each unit's tag
make releases [U=web]                # history and the last attempts
make health [U=web]
make deploy U=web T=v0.1.0-alpha03
make rollback U=web [STEPS=2 | TO=v0.1.0-alpha01] [YES=1]
make backup DB=kuloffice            # DB=blnk is also supported
make restore DB=kuloffice FILE=state/backups/kuloffice/… YES=1
```

One deploy runs at a time; the others wait. Everything it keeps is in
`state/` (gitignored): the history per unit, `releases.log`, the last 5
backups per database, the data saved by resets (kept until the unit's next
minor), and the login theme copied out of the running Keycloak image
(`KEYCLOAK_THEME_DIR`). The newest 5 tags of each image stay on disk;
Docker Hub keeps them all. A unit's first deploy records what runs now as its
first entry, so a rollback can return to it.

### Setting it up (once)

1. **The deploy user**, on the server, as root:
   `sudo sh bin/setup-deploy-user.sh`. It creates `kulpay-deploy` in the
   docker group with a random password, lets it log in with that password
   only to run `bin/kulpay-ssh` (no shell, no forwarding), shares this
   checkout with it through a `kulpay` group, and installs fail2ban. It
   prints the secrets below.
2. **Secrets** in GitHub, organisation-level, shared with the six
   repositories (commands in [../CICD.md](../CICD.md)): `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (a Docker Hub
   access token that can push to `developerspavs/*`), `DEPLOY_HOST`,
   `DEPLOY_USER`, `DEPLOY_PASSWORD`, `DEPLOY_KNOWN_HOSTS`, and `DEPLOY_PORT`
   if SSH isn't on 22.
3. **Check:** run the Server workflow with `status`.

Before each deploy or rollback the tool brings this checkout up to date
(`git pull --ff-only`), so compose changes merged here reach the server. A
local change on the server stops that (the deploy goes on with the kit as it
is, and says so). A new required setting still needs a person:
`make sync-env`, fill it in, then deploy.

### By hand

Without CI (or for kulportal), the laptop route still works:

```bash
# laptop: the unit's tags in .env, then
make images S="KULOFFICE" && make push S="KULOFFICE"
# server:
make deploy U=kuloffice T=<tag>      # or: the tag in .env, then make update
```

`make restart S=kuloffice` recreates one service: a plain `docker restart`
keeps the old environment. After a change to the realm scripts or `.env`'s
realm settings, `make init` applies it.

### KulOffice and the payments Gateway

The integration uses three independent Gateway keys. `GATEWAY_API_KEY` belongs
to KulOffice's own Gateway account and can create/read payments, incoming
transfers, bill payments and its own webhook. `GATEWAY_SERVICE_API_KEY` is the
operator-issued cross-account service key used only for authenticated payment
and payable read-back, fee instructions, merchant webhook provisioning and
merchant provisioning (IG-67: the merchant's tenant, Payment Acceptance
applications, application-bound keys and connector sessions, through the
narrow `service:accounts:write`, `service:applications:write`,
`service:keys:write` and `service:connector-sessions:write` scopes). It never
holds `accounts:write`. Turn provisioning on with
`KULOFFICE_PAYMENT_ACCEPTANCE_PROVISIONING_ENABLED=true` once the Gateway serves
those scopes; `bin/kulpay` generates its seal key
(`KULOFFICE_PAYMENT_ACCEPTANCE_SECRET_SEAL_KEY`) into `.env` when empty.

Since IG-84 KulOffice needs, besides the above: `KULOFFICE_ADMIN_BASIC_ENABLED`
(true by default here, for provisioning's bootstrap; set it to `false` in `.env`
and `make restart S=kuloffice` once provisioning ran), an admin password of at
least 20 characters (`bin/kulpay` generates one when `KULOFFICE_ADMIN_PASSWORD`
is empty), `KULOFFICE_AUTH_SERVICE_ISSUER` (default: the `REALM` realm under
`KEYCLOAK_PUBLIC_URL`; production refuses to start without it while the
Gateway client or a worker is configured), and the `OLA_SMS_*` values: KulOffice
has no SMS defaults any more, so SMS is off without them.

Since Gateway IG-83, the gateway believes `X-Forwarded-For` only from
`KULPAY_TRUSTED_PROXIES` (default: loopback and `STACK_GATEWAY`), and
maker-checker compares principals: the `operator` key carries
`principal: operator:kit-operator`, so it can prepare or approve a request but
never both; the other side needs a different principal.
`GATEWAY_ADMIN_KEY` configures connector bindings and the one platform event
sink. Do not combine them: their separation is part of the tenant boundary.

Before the fresh Gateway database is first started, set a stable,
27-character alphanumeric `GATEWAY_ACCOUNT_ID`. The generated Gateway YAML
binds all three keys to that tenant. Also set a distinct
`GATEWAY_KULOFFICE_CLIENT_SECRET`; `make init` creates or updates the
`kulpay-gateway` Keycloak service client and gives its tokens only KulOffice's
API audience.

After Gateway, Keycloak and KulOffice are running, provision signed event
delivery:

```bash
make gateway-kuloffice
```

The command idempotently creates KulOffice's account webhook for
`incoming_transfer.*` and the platform `payment.*` event sink. Their one-time
signing secrets are written to the ignored `.env` without being printed, then
KulOffice is recreated. If an endpoint exists but `.env` lost its secret, the
command rotates that secret with a 24-hour grace period. The deployment tool's
`bin/kulpay provision` action includes this step.

KulPay's own purchases (a business bill paid on its Gateway invoice link, a
recharge) can be paid with the KulPay wallet at the Gateway's hosted checkout:

```bash
make platform-wallet
```

writes one live `kulpay_balance` binding on the platform account
(`GATEWAY_ACCOUNT_ID`) with the merchant bindings' KulOffice client and
wake-up secret, destination account and product `platform`, and
`application_id` = `KULOFFICE_CHECKOUT_PROVIDER_PLATFORM_APPLICATION_ID`
(default `kulpay-platform`, the same value KulOffice reads). KulOffice then
reserves the customer's Conta Pagamento and, on capture, moves it into its
external funds balance (the reverse of a top-up); a void releases it and a
refund moves it back. No merchant and no pricing plan: the Gateway's fees are
already in the checkout total. Safe to repeat. It needs a KulOffice image with
the platform checkout (`claude/platform-wallet`); before that KulOffice
refuses the binding's authorizations.

Incoming transfers, supply, Payment Acceptance and reconciliation remain off
by default. Enable them in that order after each smoke test. Supply must not be
enabled until `KULOFFICE_SUPPLY_CLEARING_BALANCE` names the real BLNK clearing
balance. The two Gateway bases are deliberately different: top-up charge calls
use the public root `http://gateway:9090`, while every `/v1` account/service
call uses `http://gateway:9091/v1`.

## Day to day

```bash
make ps
make logs S=kuloffice
docker compose exec db pg_dump -U postgres kuloffice > kuloffice-$(date +%F).sql   # back up a database
```

KYC images that are never accepted expire from the `kyc-pending` bucket after
`PENDING_EXPIRY_DAYS` (MinIO's lifecycle rule, set by `minio-init`).

## kulportal

The review portal is kulportal2, released like the others: a tag on its `main`
(`v0.1.0-alpha00`, …) builds `developerspavs/kulpay-kulportal` and deploys it.
The first deploy generates `KULPORTAL_CLIENT_SECRET` and `KULPORTAL_SESSION_SECRET`
into `.env` and makes the `kulportal` client in the workforce realm (init keeps
it, also after a Keycloak reset). Apache serves it from `apache/kulportal.conf`
at `KULPORTAL_PUBLIC_URL`. Reviewers are operators: `make operator`.

## Things that bite

- **`KEYCLOAK_PUBLIC_URL` is the token issuer and the passkey rpId.** Changing
  it invalidates every token and passkey. Decide it before the first `make init`.
- **The login theme is mounted** over the image's. Since CI it travels in the
  Keycloak image and a deploy copies it out (`state/theme/kulpay`), so it
  always matches. Edits there last until the next Keycloak deploy; change
  intaka's `demo/theme` instead.
- **`make clean` deletes every database and stored file**, and asks first.
- **The token panel holds live tokens.** Never serve it without the password.
- **The PSP simulator approves top-ups.** Never serve it without the password,
  and never run it on a server whose gateway holds real provider credentials.
