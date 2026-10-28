# Bank deployment kit

This folder contains the production-only, single-host Docker Compose package
for installing KulPay in a bank environment.

Start with the [installation manual](INSTALLATION_MANUAL.md). It covers the
architecture, prerequisites, image and license material, configuration,
installation, provisioning, database layout, Redis usage, backups, upgrades
and operational controls.

Supporting material:

- [Acceptance checklist](ACCEPTANCE.md)
- [Network and firewall matrix](NETWORK.md)
- [Release manifest template](RELEASE-MANIFEST.example.md)
- [Environment template](.env.example)
- [KulOffice environment template](kuloffice.env.example)
- [Compose definition](compose.yaml)
- [Reverse-proxy example](reverse-proxy/nginx.conf.example)

The package deliberately excludes the PSP simulator, token panel, development
SMS inbox, demo users and demo data. Gateway uses
`developerspavs/kulpay-gateway:<approved-release-tag>`; both Gateway and
KulOffice still require their corresponding licensed entitlements.

## FNB cash-deposit pilot

The FNB workflow is declarative and resumable. Copy
`provisioning/fnb-pilot.example.yaml` to `fnb-pilot.yaml`, fill the bank's
legal, KYB, contract and statement details, then run:

```bash
ENV_FILE=.env sh scripts/provision-psp.sh plan
ENV_FILE=.env sh scripts/provision-psp.sh apply
```

These are the bank-server commands and require only the existing Docker Compose
installation; GNU Make is not required. The equivalent Make targets remain as
optional operator shortcuts on hosts where Make is installed.

The provisioner creates or reuses the maker, checker and FNB technical users;
creates a local test business and postpaid biller; creates RF and QR invoices;
submits and reviews the PSP application; performs both sides of every
maker-checker action; validates the statement profile; runs certification; and
stops at `pilot`. It never bypasses a gate. If certification depends on FNB
work that is not ready yet, the command exits with status 3 and a
`waiting_for_certification` report. Re-run it after the integration is fixed.

One-time keys and temporary passwords are written only to
`fnb-pilot-output/secrets.json` with mode `0600`. The non-secret operational
summary is `fnb-pilot-output/readiness-report.json`. Keep both outside source
control and move the credentials into the bank's secrets vault immediately.

If the controlled pilot must be stopped, run
`ENV_FILE=.env sh scripts/provision-psp.sh rollback`. It first empties
the pilot merchant allow-list, then uses the configured maker and checker
Gateway principals to suspend the PSP. The PSP, keys, approvals and audit
history remain in place; suspension makes the account and its keys unusable.
Reinstatement is intentionally not automated.

The included launch-matrix override enables only the already-modelled live
`partner_api/cash` cash-deposit route needed by this controlled pilot. All
other routes retain the approved matrix settings.
