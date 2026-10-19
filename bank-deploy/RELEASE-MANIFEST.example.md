# KulPay bank release manifest

Complete and sign this manifest for each installation or upgrade. Replace all
example values; do not put secrets or licenses in this file.

- Release identifier: `YYYY.MM.DD-N`
- Target environment: `production`
- Target architecture: `linux/amd64`
- Compose source revision: `<git commit>`
- Prepared by: `<name>`
- Approved by: `<bank change reference>`

| Component | Repository | Tag | Resolved SHA-256 digest | SBOM/scan evidence |
|---|---|---|---|---|
| Intaka/Keycloak | `developerspavs/kulpay-keycloak` | `<tag>` | `sha256:<digest>` | `<reference>` |
| KulOffice | `developerspavs/kulpay-kuloffice` | `<tag>` | `sha256:<digest>` | `<reference>` |
| Gateway | `developerspavs/kulpay-gateway` | `<tag>` | `sha256:<digest>` | `<reference>` |
| KulPay Web | `developerspavs/kulpay-web` | `<tag>` | `sha256:<digest>` | `<reference>` |
| KulPortal | `developerspavs/kulpay-kulportal` | `<tag>` | `sha256:<digest>` | `<reference>` |
| Solange | `developerspavs/kulpay-solange` | `<tag>` | `sha256:<digest>` | `<reference>` |
| Solange Console | `developerspavs/kulpay-solange-console` | `<tag>` | `sha256:<digest>` | `<reference>` |
| Boquisso | `developerspavs/kulpay-fileserver` | `<tag>` | `sha256:<digest>` | `<reference>` |
| Provisioner | `developerspavs/kulpay-tools` | `<tag>` | `sha256:<digest>` | `<reference>` |
| BLNK | `jerryenebeli/blnk` | `<tag>` | `sha256:<digest>` | `<reference>` |
| PostgreSQL | `postgres` | `17-alpine` | `sha256:<digest>` | `<reference>` |
| Redis | `redis` | `7.2.4-alpine` | `sha256:<digest>` | `<reference>` |
| Typesense | `typesense/typesense` | `29.0` | `sha256:<digest>` | `<reference>` |
| MinIO / mc | `<approved mirror>` | `<tag>` | `sha256:<digest>` | `<reference>` |

## Commercial controls

- KulOffice entitlement/reference: `<non-secret reference>`
- Gateway entitlement/reference: `<non-secret reference>`
- License validity checked by: `<name/date>`
- Pavulla support contact: `<contact>`

## Verification

- [ ] Every Compose image resolves to a digest listed above.
- [ ] Checksums/signatures were verified before import into the bank registry.
- [ ] No image uses `latest` or a mutable reused release tag.
- [ ] Database migration and rollback compatibility were reviewed.
- [ ] The acceptance checklist is attached to the change record.
