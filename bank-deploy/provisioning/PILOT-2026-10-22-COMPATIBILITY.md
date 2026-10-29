# Gateway alpha14 compatibility audit

This audit covers every Gateway endpoint called by `psp_provision.py` when
`deployment.gateway_profile` is `pilot-2026-10-22`.

## Locked build provenance

- Image: `localhost/kulpay-gateway:v0.1.1-alpha14`
- Image ID: `sha256:8ae4aee9a79b15b761e5b31c9a2a60c68f48e374644e4f93c7fceebe77824451`
- Image creation: 2026-10-22 11:49:48 UTC
- Source revision: `15935f3f42545feb3aa5a945062fb99f93f1cc5a`
  (`Licence always enforced: no valid licence, nothing works`)

The source revision is pinned by ancestry and build time: it is between
`e85867c` and `59a92a2` and was committed 38 seconds before the image was
created. The executable was built with `-trimpath` and does not contain a
`vcs.revision` field, so the image itself cannot provide a stronger embedded
revision identifier without being rebuilt (which this release does not do).

Public endpoints are on port 9090. Admin and partner `/v1` APIs are on the
management listener, port 9091, in this build.

## Endpoint table

| Caller | Method and path | alpha14 | Compatibility finding |
|---|---|---:|---|
| public | `POST /v1/psps/applications` | present | Application payload accepted. |
| public | `POST /v1/psps/applications/{id}/submit` | present | Draft-token header accepted. |
| public | `GET /onboarding` | present | Establishes application and CSRF cookies. |
| public | `POST /onboarding/sandbox-key` | present | One-time test key is returned in HTML. |
| public | `POST /onboarding/live-key` | present | One-time live key is returned in HTML. |
| public | `POST /v1/biller/invoices` | present | Test biller key and invoice batch payload accepted. |
| public | `GET /v1/biller/invoices/{number}` | present | Returns the test invoice and artifacts. |
| admin | `GET /v1/admin/accounts` | present | Same response envelope used by the provisioner. |
| admin | `POST /v1/admin/accounts` | present | `business_name`, `country`, and `status` accepted; `test_business.country` is valid. |
| admin | `POST /v1/admin/accounts/{id}/keys` | present | Biller key is returned once under `key.secret`. |
| admin | `GET /v1/admin/approvals` | present | `subject_id` and `pending` query parameters accepted. |
| admin/checker | `POST /v1/admin/approvals/{id}/decide` | present | Distinct checker principal is enforced by the approval service. |
| admin | `GET /v1/admin/billers/{code}` | present | Biller and products envelope matches. |
| admin | `POST /v1/admin/billers` | present | `country` is accepted and required by the service model. |
| admin | `POST /v1/admin/billers/{code}/products` | present | Product payload accepted. |
| admin | `POST /v1/admin/billers/{code}/status` | present | Produces a maker/checker approval. |
| admin | `GET /v1/admin/psps` | present | Used for resume/adoption and rollback. |
| admin | `GET /v1/admin/psps/{id}` | present | PSP envelope matches. |
| admin | `POST /v1/admin/psps/{id}/transitions` | present | Lifecycle transition payload matches. |
| admin | `GET /v1/admin/psps/{id}/kyb` | present | Documents and screenings are returned. |
| admin | `POST /v1/admin/psps/{id}/kyb/documents` | present | Multipart document upload accepted. |
| admin | `POST /v1/admin/psps/{id}/kyb/documents/{doc}/review` | present | Review payload matches. |
| admin | `POST /v1/admin/psps/{id}/kyb/screenings` | present | Screening payload matches. |
| admin | `POST /v1/admin/psps/{id}/kyb/risk-tier` | present | Risk-tier payload matches. |
| admin | `POST /v1/admin/psps/{id}/kyb/decision` | present | Produces the KYB maker/checker approval. |
| admin | `GET /v1/admin/psps/{id}/configs?kind=…` | present | Active versions use the expected envelope. |
| admin | `POST /v1/admin/psps/{id}/configs/{kind}` | present | Commercial terms and capability matrices produce approvals. |
| admin | `POST /v1/admin/psps/{id}/contract` | present | Multipart signed contract accepted. |
| partner | `GET /v1/psps/{id}/statement-profiles` | present | Served on 9091, not 9090. Multiple profiles are already supported. |
| partner | `POST /v1/psps/{id}/statement-profiles/preview` | present | Multipart profile/sample accepted; alpha14 parses CSV and camt.053. |
| partner | `PUT /v1/psps/{id}/statement-profiles` | present | Whole profile list and reason payload accepted. |
| admin | `GET /v1/admin/safeguarding/accounts` | present | Registration predates alpha14. |
| admin | `POST /v1/admin/safeguarding/accounts` | present | `account`, `currency`, and `bank` payload accepted. |
| partner | `GET /v1/webhook-endpoints` | present | Served on 9091 with the partner key. |
| partner | `POST /v1/webhook-endpoints` | present | Test/live mode, URL and event filters accepted; secret returned once. |
| admin | `POST /v1/admin/psps/{id}/certification/runs` | present | JSON first run and multipart statement rerun are both supported. |
| admin | `GET /v1/admin/psps/{id}/certification/runs` | present | Used to resume a prior run. |
| admin | `GET /v1/admin/psps/{id}/certification/runs/{run}` | present | Run and case response matches. |
| partner | `GET /v1/certification/tasks` | **missing** | Added later at `96e5b12`; the explicit pilot profile skips it without probing. |
| admin | `PUT /v1/admin/psps/{id}/pilot` | present | Limits, merchant allow-list, routing weight and reason accepted. |
| partner | `POST /v1/api-keys` | present, scope changed | Restricted live key type and expiry are accepted. Alpha14 refuses the later operator-only `bills:artifacts` scope on partner-issued keys, so the pilot profile requests only partner-safe transaction, bill, event and reconciliation scopes. |
| partner | `DELETE /v1/api-keys/{id}` | present | Revokes the broad one-time pilot key. |
| admin | `POST /v1/admin/psps/{id}/suspension` | present | Rollback produces a maker/checker approval. |
| admin | `GET /v1/admin/launch-matrix` | present | Expanded routes include `enabled`; payload matches the launch check. |

## Behavioural differences

Alpha14 builds a 14-case certification suite with 12 mandatory cases when the
capability matrix includes the otherwise-unused `SALE/bank_transfer` row. The
row runs only against the Gateway sandbox mock and does not create an FNB
connector binding. The later incoming-funding task suite is absent, so the
pilot profile keeps the row and skips task discovery deterministically.

The statement rerun is present: the second request carries `rerun_of` and a
multipart `statement` file, and passed cases are carried from the first run.
The launch-matrix endpoint and expanded route response are also present.

Safeguarding account registration and multiple statement profiles are present
in alpha14. What alpha14 does **not** contain is the later `bc99a2c` aggregate
calculation that adds provider custody to held funds and KulOffice e-money to
obligations. Its daily proof covers the Gateway ledger and registered bank
account statements only. That image limitation is documented, not hidden by
the provisioner.

The embedded launch matrix keeps live `partner_api/cash` deposits disabled.
The bank deployment therefore uses `gateway/launch_matrix.json`, derived from
the embedded `2026-10-12.3` matrix with only that controlled live route enabled.
Every unlisted route and every `off_net` movement remains refused.

Alpha14 recognises the FNB `cash_deposit` capability only when the bank kit's
existing `kulpay_cms` connector is enabled. Rev4 preserves the rev3 connector
configuration and adds no new external connector or image.
