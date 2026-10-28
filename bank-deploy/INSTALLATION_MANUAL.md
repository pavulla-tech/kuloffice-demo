# KulPay bank installation manual

This folder is the production-only, single-host Compose distribution for a
bank installation. It deliberately contains no PSP simulator, token panel,
development SMS inbox, demo users, demo data or automatic simulator bindings.

It is a simple deployment, not a highly available one. PostgreSQL, MinIO,
Redis and Typesense are local persistent services. If the bank requires
clustered data services, HSM-backed secrets or multi-host failover, those are
an infrastructure design change and must be agreed before installation.

## What runs

| Component | Exposure | State/purpose |
|---|---|---|
| `keycloak` (Intaka image) | TLS proxy | Intaka customer and workforce identity, phone/PIN/passkey flows |
| `kuloffice` | TLS proxy | Licensed business core and API |
| `web` | TLS proxy | Customer browser application and payment approval pages |
| `kulportal` | TLS proxy | Workforce review/back-office portal |
| `solange`, `solange-console` | TLS proxy | QRCode/Solange edge, webhooks and staff console |
| `gateway` | Public listener through TLS proxy | Licensed payment core; management listener remains internal |
| `blnk-server`, `blnk-worker` | Internal | Ledger API and durable queue processor |
| `blnk-redis` | Internal, persistent | BLNK durable work queue; no other service uses Redis |
| `blnk-typesense` | Internal, persistent | BLNK search projection |
| `minio` | Internal, persistent | S3-compatible object storage for KYC files |
| `fileserver` | Internal | Boquisso access layer in front of MinIO |
| `db` | Internal, persistent | PostgreSQL databases for KulOffice, Keycloak, Solange, BLNK and Gateway |
| `provisioner` | On demand | Realms, clients, staff, licenses and integration secrets |

`db-init`, `minio-init`, `gateway-config` and `solange-migrate` are idempotent
one-shot jobs. They are expected to exit successfully rather than remain
running.

## Prerequisites

- A dedicated Linux host with Docker Engine and Compose v2.
- Capacity agreed from load testing. As an initial non-HA baseline, reserve at
  least 8 CPU cores, 16 GiB RAM and separate monitored storage for Docker data
  and backups; this is not a sizing guarantee.
- Bank DNS names and TLS certificates for the seven public URLs in `.env`.
- Access to an approved container registry or an offline image bundle.
- Final image tags/digests, SBOMs, signatures/checksums and scan reports.
- KulOffice and Gateway entitlements supplied by Pavulla.
- SMS, biometric/KYC and payment-provider endpoints reachable through the
  bank's approved egress controls.
- NTP/time synchronization. Tokens, OTPs, signatures and certificates depend
  on correct time.
- Bank-approved encryption for Docker volumes and backup media. If policy
  requires application-level object encryption, configure MinIO with the
  bank's supported KMS before accepting KYC documents.

Inbound traffic is HTTPS only through the bank load balancer or reverse proxy.
PostgreSQL, MinIO, Redis, Typesense, Boquisso, BLNK and the Gateway management
listener are not published. The example proxy is
[`reverse-proxy/nginx.conf.example`](reverse-proxy/nginx.conf.example); the
complete port and egress list is in [`NETWORK.md`](NETWORK.md).

## Release and license material

The installation package must contain a release manifest with every image tag
and its resolved digest. Never use `latest`, and never rebuild an approved tag.
For an offline bank registry, mirror the exact images and change only the
`*_IMAGE` values. Start from
[`RELEASE-MANIFEST.example.md`](RELEASE-MANIFEST.example.md).

For Gateway, this package uses the following image convention:

```dotenv
GATEWAY_IMAGE=developerspavs/kulpay-gateway
GATEWAY_TAG=<approved-release-tag>
```

The tag must be supplied with the bank release and recorded with its resolved
digest in the release manifest. Access to the image does not replace the
Gateway license entitlement.

KulOffice activation is performed by the provisioner using
`KULOFFICE_LICENSE_KEY`. The matching license-signing private key remains with
Pavulla and must not be copied into the bank repository or host. Gateway
entitlement is delivered according to the licensed Gateway release procedure;
record its verification in the acceptance report.

## Prepare configuration

```sh
cd bank-deploy
make setup
$EDITOR .env
$EDITOR kuloffice.env
make config
```

For the FNB cash-deposit pilot, also prepare its non-secret provisioning input:

```sh
cp provisioning/fnb-pilot.example.yaml fnb-pilot.yaml
chmod 600 fnb-pilot.yaml
```

Fill every value marked `REQUIRED`, including the KYB evidence, signed
contract and a real FNB sample statement. The referenced files must be present
on the application server when provisioning runs. Place them beside the YAML
and use relative paths, so the entire input directory can be mounted read-only.
Do not place API keys, passwords or license tokens in this YAML.

Generate every secret independently. Recommended commands are
`openssl rand -hex 32` for API/session keys and
`openssl rand -base64 32` for 32-byte encryption keys. Generate the BLNK
tokenization value with `openssl rand -base64 24`, matching the current BLNK
integration contract. Do not paste command output into ticketing systems or
shell history shared with other operators.

Important immutable choices:

- `KEYCLOAK_PUBLIC_URL` is the token issuer and passkey relying-party host.
  Changing it later invalidates tokens and passkeys.
- `GATEWAY_ACCOUNT_ID` is the stable 27-character Gateway tenant boundary.
- `GATEWAY_ENCRYPTION_KEY` protects stored connector credentials. Losing or
  changing it makes those credentials unreadable.
- Application database-role passwords are reconciled by `db-init`, but rotating
  them requires a controlled restart of dependent services. PostgreSQL's
  `DB_ROOT_PASSWORD` is established on the first empty-volume start and must be
  rotated inside PostgreSQL through a separate approved procedure.
- Changing tokenization, session or webhook secrets can invalidate protected
  data or in-flight sessions. Follow a key-rotation runbook.

Keep `.env` and `kuloffice.env` at mode `0600`. Environment variables provide
the simple baseline requested for this package. If bank policy requires a
vault, render these files immediately before Compose runs, restrict them to the
deployment account, and securely erase the rendered copy after shutdown.

## PostgreSQL layout

The bundled PostgreSQL instance is internal and creates these isolated roles
and databases:

| Database/role | Client |
|---|---|
| `kuloffice` | KulOffice |
| `keycloak` | Intaka/Keycloak |
| `solange` | Solange QR |
| `blnk` | BLNK server and worker |
| `gateway` | Payments Gateway |

Applications connect through the private Compose network to `db:5432`; there
is no host port. `db/init.sh` is idempotent and updates each role's password on
start. The PostgreSQL superuser is used only by that one-shot initialization
and backup operations.

This single-node package uses unencrypted traffic inside its private bridge.
If the bank supplies external PostgreSQL, require TLS with certificate
verification, separate roles/databases, supported PostgreSQL 17 compatibility,
and an agreed migration/backup procedure. Do not expose the bundled database
to emulate that design.

Boquisso does not receive MinIO's root credential. `minio-init` creates a
dedicated account and policy limited to the three configured object buckets.
The root credential is retained only by MinIO and its one-shot initializer.

## Install

1. Verify the release manifest, resolved image digests, signatures/checksums and architecture.
2. Place the folder on the host and complete `.env` and `kuloffice.env`.
3. Configure DNS and the TLS proxy. Keep `PUBLISH_ADDRESS=127.0.0.1` when the
   proxy runs on the same host. For a remote bank load balancer, bind a
   dedicated private host address, set `ALLOW_REMOTE_PROXY=true`, and restrict
   the firewall source to that load balancer.
4. Validate and pull images:

   ```sh
   make config
   make pull
   ```

5. Start the stack and wait for health:

   ```sh
   make start
   make ps
   make health
   ```

6. Provision the customer/workforce realms, production clients, KulOffice
   license and both identity providers:

   ```sh
   make provision
   ```

   This operation is idempotent. It intentionally does not create a token-panel
   client, demo reviewer or USSD client. Do not reset an existing realm during
   a normal deployment because doing so rotates signing keys and deletes users.

7. Add named workforce operators:

   ```sh
   make operator EMAIL=ana@bank.example FIRST=Ana LAST=Macuacua
   make operator EMAIL=rui@bank.example FIRST=Rui LAST=Lopes ROLE=ADMIN SOLANGE=admin
   ```

8. Provision QR and signed Gateway event delivery:

   ```sh
   make qr-provision
   make gateway-provision
   ```

   Generated integration secrets are written into `.env` without being printed.

9. Validate and provision the controlled FNB cash-deposit pilot:

   ```sh
   ENV_FILE=.env sh scripts/provision-psp.sh plan
   ENV_FILE=.env sh scripts/provision-psp.sh apply
   ```

   These commands use Docker Compose directly through the included wrapper;
   Make is not required on the bank server.

   The command is resumable and stops at `pilot`. A status of 3 with
   `waiting_for_certification` means the FNB integration must complete or fix
   the mandatory certification cases; run the same command again afterwards.
   Store `fnb-pilot-output/secrets.json` in the bank's secrets vault. To stop
   the pilot without deleting evidence or audit history, run
   `ENV_FILE=.env sh scripts/provision-psp.sh rollback`; this removes
   eligible pilot merchants and then suspends the PSP through maker/checker
   approval.

10. After provisioning succeeds, set
   `KULOFFICE_ADMIN_BASIC_ENABLED=false` and run:

   ```sh
   make restart S=kuloffice
   ```

11. Complete [`ACCEPTANCE.md`](ACCEPTANCE.md) before enabling money movement.

## Real payment connectors

This package never creates simulator bindings. Gateway starts without provider
credentials. A bank maker loads the approved M-Pesa, e-Mola, card or bank-rail
binding through the Gateway management API; a distinct checker approves the
change. `GATEWAY_ADMIN_KEY` and `GATEWAY_CHECKER_KEY` have different principals
for that reason.

Connector credentials must be delivered through the bank's secret ceremony,
encrypted at rest by `GATEWAY_ENCRYPTION_KEY`, and excluded from Compose,
source control, logs and screenshots. Configure provider callback URLs against
`GATEWAY_PUBLIC_URL` and validate signatures and source restrictions.

All money-moving integrations default to `false`. Enable and smoke-test one at
a time. Never enable supply until `KULOFFICE_SUPPLY_CLEARING_BALANCE` identifies
the approved real BLNK clearing balance.

## Operations

```sh
make ps
make health
make logs S=kuloffice
make restart S=kuloffice
make backup
make stop
```

`make restart` recreates containers so environment changes take effect. A plain
container restart retains the old environment and must not be used for a
configuration change.

`make backup` creates PostgreSQL custom-format dumps and a MinIO data archive
under `backups/<UTC timestamp>/`, plus checksums. It is a baseline facility,
not the bank's complete backup system. Encrypt and copy the output off-host.
For a transactionally controlled backup, quiesce writes or use the bank's
approved PostgreSQL and object-storage snapshot facilities. Redis AOF is part
of BLNK's durable processing state and must be protected together with BLNK's
database; Typesense is a rebuildable projection.

Restore is deliberately not automated because it is destructive. The restore
runbook must state the target host, maintenance window, backup checksums,
database ownership, MinIO version, BLNK Redis state, validation queries and
formal approval. Always restore into an isolated environment and complete the
acceptance checklist before switching traffic.

## Upgrade and rollback

1. Back up persistent state and record current image digests.
2. Review release notes and database migrations.
3. Change only the approved image tags and verify their resolved digests.
4. Run `make config`, `make pull`, then `make start`.
5. Run `make health` and the affected acceptance tests.
6. Roll back only when the previous binaries are compatible with migrations
   already applied. Otherwise restore the coordinated backup.

The bank must define RPO/RTO, retention, off-host encryption, monitoring and
incident escalation. At minimum alert on unhealthy containers, restart loops,
PostgreSQL/volume capacity, Redis persistence failures, MinIO errors, failed
webhooks, reconciliation differences and certificate expiry.

## Removal and safety

`make stop` preserves every volume. This folder intentionally provides no
`clean` target: deleting PostgreSQL, MinIO, Redis or ledger state is a governed
destructive operation and must follow the bank's data-retention and approval
process.
