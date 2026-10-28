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

Certification runs in rounds. It registers FNB's test webhook endpoint
(`partner.webhooks.test_url`) with FNB's sandbox key, so the webhook cases can
sign and send real webhooks; the signing secret goes to `secrets.json`. The
first round uses the sample statement; its statement case then names the
sandbox payments FNB's statement must list, written to
`fnb-pilot-output/statement-request.json`. Put FNB's statement (CSV:
`reference,amount,currency,date`) in `partner.certification_statement_file`
and run `apply` again: it repeats the failed cases with that statement and
keeps the passed ones. FNB's live webhook endpoint (`partner.webhooks.live_url`)
is registered on entering the pilot.

A bank that takes deposits and transfers for KulPay accounts (incoming
funding) also performs tasks during each run: with its sandbox key it does a
name lookup, reports an incoming transfer, reports it again, and takes a cash
deposit (intent and confirmation), each within the run's deadline (about 10
minutes). The provisioner prints the tasks as `WAIT` lines when it starts the
run and writes them to `fnb-pilot-output/certification-tasks.json`
(`GET /v1/certification/tasks` with the sandbox key lists them too). Their
transfers and deposits are the payments the statement round then names.

The KulPay dev kit runs the same provisioner with the PSP simulator as the
bank (`simulator-bank.example.yaml`, `make simulator-bank` in `deploy/`): the
simulator receives its keys and webhook secrets, does the run's tasks itself
(asked right after each start, and on its own every 30 s) and answers the
statement round itself.

A bank holding KulPay's client funds sends one more statement: its trust
account's end of day, with opening and closing balances (camt.053), which the
Gateway's daily safeguarding check reads. Declare it in
`partner.statement_profile.additional_profiles` (`{sample_file, profile}`,
installed beside the main profile, each sample previewed first; a re-run adds
the ones the Gateway lacks, even after certification) and the account in
`partner.safeguarding_accounts` (`{account, currency, bank}`, registered once
with the Gateway admin key). Both stay empty in `fnb-pilot.example.yaml` until
FNB holds the account; the simulator's YAML fills them (`simbank-trust-eod`,
`SIMBANK-TRUST-001`) and names its trust profile in
`simulator.trust_statement_profile`. The readiness report lists the installed
profiles and safeguarding accounts.

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
