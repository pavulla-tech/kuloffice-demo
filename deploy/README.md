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
  `KULOFFICE_DIR/keys/public.pem.base64`; `make license` signs with the private
  key beside it. Keep that pair: a license only verifies against its own key.
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

**6. Solange's app for KulPay** (once Solange has staff):

```bash
docker compose exec solange solange app create -slug kulpay-app -name "KulPay" -prefix k
docker compose exec solange solange key create -app kulpay-app -mode live -name kuloffice
```

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

## Updating

```bash
# laptop: new tags in .env, then
make images S="KULOFFICE WEB" && make push S="KULOFFICE WEB"
# server: the same tags in .env, then
make update
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
- **The login theme is mounted** (`theme/kulpay`) over the image's. It must match
  the image's templates; refresh both together (`make theme`, `make images S=KEYCLOAK`).
- **`make clean` deletes every database and stored file**, and asks first.
- **The token panel holds live tokens.** Never serve it without the password.
