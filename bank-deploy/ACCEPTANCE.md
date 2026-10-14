# Installation acceptance checklist

Record the date, operator, release manifest, evidence links and result for each
item. No financial feature is enabled merely because the containers started.

## Platform

- [ ] Approved image tags/digests match the release manifest.
- [ ] Image signatures, checksums, SBOMs and vulnerability reports are accepted.
- [ ] `.env` and `kuloffice.env` are mode `0600` and excluded from backups/logs that lack equivalent protection.
- [ ] Only the TLS proxy/load balancer can reach the loopback application ports.
- [ ] Host time synchronization, DNS and certificate chains are healthy.
- [ ] `make health` passes and one-shot jobs exited with code zero.

## Identity

- [ ] Customer and workforce issuers match the final public Keycloak hostname.
- [ ] OTP reaches an approved test handset through the real SMS provider.
- [ ] OTP budgets and Keycloak brute-force protection are active.
- [ ] Customer web/mobile login succeeds and logout invalidates the session as designed.
- [ ] A workforce reviewer can sign into KulPortal; a customer token cannot.
- [ ] The bootstrap-only KulOffice Basic credential is disabled after provisioning.

## Data and documents

- [ ] Each application connects only with its own PostgreSQL role.
- [ ] No PostgreSQL, Redis, Typesense, MinIO or Gateway management port is externally published.
- [ ] KYC upload/download succeeds through KulOffice and Boquisso.
- [ ] Volume/backup encryption and any required MinIO KMS integration are verified.
- [ ] Abandoned KYC objects expire according to `PENDING_EXPIRY_DAYS`.
- [ ] Backup artifacts are encrypted, copied off-host and restore-tested.

## Ledger and payments

- [ ] BLNK topology bootstrap completes and balances use the production environment.
- [ ] Gateway maker and checker use distinct principals and credentials.
- [ ] Real connector credentials are loaded through the approved ceremony.
- [ ] Provider callback signatures, source controls and idempotency are tested.
- [ ] Gateway-to-KulOffice event signatures are provisioned and verified.
- [ ] A low-value payment is authorized, settled, posted to BLNK and visible in KulOffice.
- [ ] Failed, timed-out and duplicate provider requests do not double-post.
- [ ] Reconciliation reports the acceptance transactions without unexplained differences.
- [ ] Features were enabled individually in this order: top-up, incoming transfers, supply, Payment Acceptance, reconciliation.

## QR and operations

- [ ] `make qr-provision` succeeds without printing the generated secrets.
- [ ] A QR resolves through the public scan hostname and its webhook reaches KulOffice.
- [ ] QR console roles enforce viewer/developer/admin separation.
- [ ] Alerting covers container health, disk, PostgreSQL, Redis, MinIO, certificate expiry and failed webhooks.
- [ ] Upgrade, rollback, database restore and incident contacts are documented and exercised.
