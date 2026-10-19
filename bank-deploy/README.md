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
