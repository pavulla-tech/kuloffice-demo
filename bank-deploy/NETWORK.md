# Network and firewall matrix

Use the final bank hostnames from `.env`; the example names below are not
production values. All public traffic must traverse the bank TLS proxy or load
balancer. With a host-local proxy, Compose ports remain on `127.0.0.1`. A
remote load balancer requires a dedicated private `PUBLISH_ADDRESS`,
`ALLOW_REMOTE_PROXY=true`, and a firewall allowlist containing only its source.

## Inbound through TLS proxy

| Public function | Default host port | Consumers |
|---|---:|---|
| Intaka/Keycloak | 9180 | Customer apps, workforce apps, service-token clients |
| KulOffice API | 9280 | Mobile/web clients, Solange and Gateway signed events |
| KulPay Web | 9380 | Customer browsers and checkout approval redirects |
| Gateway public API/callbacks | 9480 | Approved PSPs and customer checkout flows |
| Gateway operator UI (`/admin` only) | 9481 | Authorized workforce browsers through the payments hostname |
| Solange QR edge | 9580 | QR scanners and KulOffice |
| Solange Console | 9680 | Authorized staff browsers |
| KulPortal | 9780 | Authorized workforce browsers |

The proxy should accept only HTTPS, use bank-approved protocols/ciphers, add
forwarded host/protocol/address headers, enforce request limits and send logs
to the bank SIEM. Restrict workforce consoles by the bank's access policy.
Server-side applications resolve the public Keycloak and KulOffice hostnames
to `TLS_PROXY_ADDRESS` so issuer discovery and signed webhooks traverse the
same TLS proxy without depending on external DNS hairpin routing. Its default
is the Compose host bridge gateway; set it to the reachable private load
balancer address when TLS terminates remotely.
In that remote case, also replace `KULPAY_TRUSTED_PROXIES` with the load
balancer's exact private address or smallest approved CIDR.

## Container-internal only

| Port | Service | Allowed callers |
|---:|---|---|
| 5432 | PostgreSQL | Five application roles and controlled backup/init jobs |
| 6379 | BLNK Redis | BLNK server and worker only |
| 8108 | Typesense | BLNK only |
| 5001 | BLNK API | KulOffice and BLNK worker |
| 9000 | MinIO S3 API | Boquisso and MinIO initialization/backup jobs |
| 8080 | Boquisso | KulOffice only |
| 9091 | Gateway management API | KulOffice and controlled provisioning jobs; the proxy may expose only its OIDC-protected `/admin` UI |

Do not publish these ports, add host mappings for them, or route them through
the public load balancer.

## Outbound allowlist

The exact destinations are installation inputs. Typical requirements are:

- bank container registry over HTTPS during installation/upgrades;
- DNS and NTP supplied by the bank;
- SMS provider HTTPS endpoint;
- contracted biometric, document-verification and NUIB HTTPS endpoints;
- each approved PSP/acquirer endpoint used by Gateway connectors;
- certificate OCSP/CRL endpoints where required by bank PKI;
- bank monitoring, log and backup destinations.

There is no required connection to a development simulator, token panel or
demo SMS service. Disable general Internet egress after the explicit allowlist
is accepted.
