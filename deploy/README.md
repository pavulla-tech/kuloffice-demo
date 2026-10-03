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
| `db` | — | — | Postgres 17: one database and role each for kuloffice, Keycloak, Solange |
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

The database passwords are used once, when Postgres first starts on an empty
volume. Changing them in `.env` later does not change the roles.

**2. Start.**

```bash
make start
make ps                      # keycloak healthy, solange-migrate exited 0
```

**3. Apache.** For each file in `apache/`: get its certificate (`certbot
certonly --apache -d <host>`), copy it to `/etc/apache2/sites-available/`,
`a2ensite`, then `systemctl reload apache2`. Once:

```bash
a2enmod proxy proxy_http headers ssl auth_basic authn_file
htpasswd -c /etc/apache2/kulpay-panel.htpasswd <user>    # the token panel's password
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
```

- **The account:** a workforce account with a temporary password (printed
  once, changed at the first sign-in).
- **`ROLE`** (default `Revisores`, KYC review permissions): a kuloffice
  operator bound to the account, holding that role.
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
docker compose exec solange wget -qO- https://core.kulpay.pavulla.com/v1/system/status
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
make backup DB=kuloffice
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

## Day to day

```bash
make ps
make logs S=kuloffice
docker compose exec db pg_dump -U postgres kuloffice > kuloffice-$(date +%F).sql   # back up a database
```

KYC images that are never accepted expire from the `kyc-pending` bucket after
`PENDING_EXPIRY_DAYS` (MinIO's lifecycle rule, set by `minio-init`).

## kulportal

Ready but off. When it is: set `KULPORTAL_TAG`, add `KULPORTAL` to the image
targets (`make images S=KULPORTAL`, `make push S=KULPORTAL`), put its settings
in `kulportal.env`, then `make start-portal` and enable `apache/kulportal.conf`.

## Things that bite

- **`KEYCLOAK_PUBLIC_URL` is the token issuer and the passkey rpId.** Changing
  it invalidates every token and passkey. Decide it before the first `make init`.
- **The login theme is mounted** over the image's. Since CI it travels in the
  Keycloak image and a deploy copies it out (`state/theme/kulpay`), so it
  always matches. Edits there last until the next Keycloak deploy; change
  intaka's `demo/theme` instead.
- **`make clean` deletes every database and stored file**, and asks first.
- **The token panel holds live tokens.** Never serve it without the password.
