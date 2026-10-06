# KulPay CI/CD

How KulPay's services reach the server: you push a tag, and GitHub Actions
tests, builds, pushes to Docker Hub and deploys. Rollbacks are a button.
This file covers how it works and what it needs. The server side (setup,
`make` targets) is in [deploy/README.md](deploy/README.md), "Releases".

## In one picture

```
git push origin v0.1.0-alpha03          (in a service repository)
        │
        ▼
release.yml (that repository)
  test ──► service.yml (kuloffice-demo, reusable)
             build ── ci/build.sh: the unit's images, same recipes as `make images`
               │      push developerspavs/kulpay-<image>:v0.1.0-alpha03
               ▼
             deploy ── SSH (password) ──► server: bin/kulpay-ssh ──► bin/kulpay deploy <unit> <tag>
                                                    git pull the kit, then:
                                                    backup → switch → health check
                                                    ok: green │ failed: back to the previous tag, red
```

## Units: what each repository ships

A unit is one repository's output. All its images carry the repository's tag.

| Repository | Branch to tag from | Unit | Images | Data a reset wipes |
|---|---|---|---|---|
| kuloffice | `merge/kanyaka` | `kuloffice` | kuloffice | kuloffice's database and its MinIO files |
| intaka | `feat/pin-login-and-demo` | `keycloak` | keycloak (with the login theme), token-panel, tools | Keycloak's database, **plus kuloffice's database and files** |
| solange | `phase0-make-safe` | `solange` | solange, solange-console | Solange's database, **plus kuloffice's QR records** |
| kulpay-webapp | `main` | `web` | web | none |
| boquisso-fileserver | `main` | `fileserver` | fileserver | none |
| kulportal | — | `kulportal` | kulportal | none (no workflow yet; deploy by hand) |

A tag only triggers a release if the tagged commit contains
`.github/workflows/release.yml`. That is why the branch matters: tag the
branch that has it, or merge the workflow into the one you tag.

## Tags and what they do

Tags look like `v0.1.0-alpha00`, `v0.1.0-alpha01`, and so on. Each repository
numbers its own.

- **A new alpha** (`v0.1.0-alpha02` → `v0.1.0-alpha03`) is an update in
  place. The unit's database is backed up, the new image started, and the
  unit health-checked: running, healthy, not crash-looping, and answering its
  own endpoint where it has one. If the check fails, the previous tag comes
  back (and the backup, if the old version can't run on the new data). The
  run turns red.
- **A new patch** (`v0.1.0-*` → `v0.1.1-*`) **or minor** (`v0.2.0-*`) is a
  reset. The unit's data, and its dependents' (table above), is saved, wiped
  and started fresh. The setup that fresh data needs runs again:
  - after Keycloak or kuloffice: `init` (realms, license, identity
    providers);
  - after Solange: a new Solange key and webhook for kuloffice.

  After a Keycloak reset, everyone signs up again and staff accounts must be
  recreated (`make operator`). If a reset fails, everything it wiped is put
  back.
- **Deploying an older tag is refused.** Use a rollback.
- **A new minor ends the previous one.** Once a unit is on `v0.2.*`, nothing
  rolls it back to `v0.1.*`.

Never move or reuse a tag: the server would not notice the new image.

## Rolling back

In kuloffice-demo: **Actions → Rollback → Run workflow**.

| Input | Meaning |
|---|---|
| unit | which service |
| steps | how many releases back (default 1) |
| to | or an exact tag from its history (overrides steps) |
| confirm | allow restoring data; needed when the rollback crosses a reset |

- **Within a version** (alpha to alpha), only the image changes. Data stays.
- **Across a reset**, the data saved just before that reset is restored, for
  every unit the reset wiped. Everything they stored since is lost. Without
  "confirm", the run stops, lists exactly what it would restore, and turns
  red. Read it, then run again with "confirm" ticked.
- **Going "forward"** to a tag that was deployed before (e.g. after rolling
  back too far) works the same way, within a version.

**Actions → Server** shows the state without changing anything:
- `releases`: each unit's history, i.e. the tags a rollback can reach;
- `status`: what runs now;
- `health`: checks the running units.

## Who gets told

GitHub's own notifications: the person who pushed the tag (or ran the
workflow) gets an email when a run fails. A deploy that rolled itself back
counts as failed. Nobody else is emailed, so look at the Actions tab, or run
**Server → releases**, which also lists the last attempts and their results.

## Secrets

All of them are **organisation secrets** in `pavulla-tech`, shared with the
six repositories below only ("selected repositories", not all 177). Verified
on the org's Free plan: the private repositories see them too.

Set or change one from a terminal (an org admin; the value is read from
stdin, so it stays out of your shell history):

```bash
R=kuloffice,kuloffice-demo,kulpay-webapp,intaka,solange,boquisso-fileserver
gh secret set KULPAY_DOCKERHUB_USERNAME --org pavulla-tech --visibility selected --repos $R
gh secret set KULPAY_DOCKERHUB_TOKEN    --org pavulla-tech --visibility selected --repos $R
gh secret set DEPLOY_HOST        --org pavulla-tech --visibility selected --repos $R
gh secret set DEPLOY_PASSWORD    --org pavulla-tech --visibility selected --repos $R
gh secret set DEPLOY_KNOWN_HOSTS --org pavulla-tech --visibility selected --repos $R
```

Each command prompts for the value. Or use the web: Organisation Settings →
Secrets and variables → Actions → New organization secret, with Repository
access set to the six repositories. A new repository joining the pipeline
must be added to each secret's list (`gh secret set … --repos` with the new
list, or the web).

`DEPLOY_USER` is already set (`kulpay-deploy`).

| Secret | Value | Used by |
|---|---|---|
| `KULPAY_DOCKERHUB_USERNAME` | the Docker Hub account that owns `developerspavs` | service repositories (build) |
| `KULPAY_DOCKERHUB_TOKEN` | a Docker Hub personal access token with **Read & Write** on `developerspavs/*` | service repositories (build) |
| `DEPLOY_HOST` | the server's address (IP or hostname) | all six |
| `DEPLOY_USER` | `kulpay-deploy` (already set) | all six |
| `DEPLOY_PASSWORD` | the password `setup-deploy-user.sh` printed | all six |
| `DEPLOY_KNOWN_HOSTS` | the server's host-key line `setup-deploy-user.sh` printed, with the address in front: `<address> ssh-ed25519 AAAA…` | all six (optional, strongly recommended) |
| `DEPLOY_PORT` | SSH port, only if it isn't 22 | all six (optional) |
| `KULPAY_DOCKERHUB_PULL_TOKEN` | not needed today; only if Docker Hub's anonymous pull limit ever gets in the way (see below) | all six (optional) |

Which repository needs which:

| Repository | Needs |
|---|---|
| kuloffice, intaka, solange, kulpay-webapp, boquisso-fileserver | `KULPAY_DOCKERHUB_USERNAME`, `KULPAY_DOCKERHUB_TOKEN`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PASSWORD`, `DEPLOY_KNOWN_HOSTS` (+ `DEPLOY_PORT`) |
| kuloffice-demo (Rollback, Server workflows) | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PASSWORD`, `DEPLOY_KNOWN_HOSTS` (+ `DEPLOY_PORT`) |

Notes:
- **Callers' secrets.** The build and deploy run in the service repository's
  context (`secrets: inherit`), with that repository's secrets.
  kuloffice-demo never needs the Docker Hub token.
- **Why `KULPAY_` on the Docker Hub ones:** a repository secret wins over an
  organisation secret of the same name. kuloffice keeps repository-level
  `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` for the `pavulla` Docker Hub account
  (its older goreleaser workflow on `main`), which would shadow the org's.
  Its `SERVER_*` and Solange's `VPS_*` are not used by these pipelines.
- **The server needs no token.** The images are public, and so is this
  repository (the only thing the server fetches from GitHub). No Docker
  login is stored on the server. Each
  deploy or rollback sends `KULPAY_DOCKERHUB_USERNAME` and
  `KULPAY_DOCKERHUB_PULL_TOKEN` over SSH on stdin (never on the command
  line). The server logs in to a throwaway Docker config for that run and
  deletes it when the run ends. Without the secret, it pulls anonymously:
  the images are public, so that works, but under Docker Hub's lower
  anonymous rate limit. `developerspavs` is a personal account, where Docker
  Hub can't limit a token to chosen repositories. Use the **Public Repo
  Read-only** scope: it pulls public images and can't push or delete. On a
  Docker Hub organisation, an organisation access token can be limited to
  the `kulpay-*` repositories instead.
- **No license secret is needed.** kuloffice's license public key is in this
  repository (`deploy/keys/kuloffice-license.pub.base64`). It is public by
  nature, and the same key the server's license was signed for.
- **Without `DEPLOY_KNOWN_HOSTS`** the runs still work but warn: the server's
  identity isn't checked, so someone impersonating it could capture the
  password.

## The server side, briefly

- **SSH access:** CI logs in as `kulpay-deploy` with a password. sshd forces
  every login of that user to `deploy/bin/kulpay-ssh`, which accepts only
  `deploy`, `rollback`, `releases`, `status` and `health` with plain
  arguments. There is no shell and no forwarding, and fail2ban guards the
  login. `deploy/bin/setup-deploy-user.sh` sets all of this up.
- **Before a deploy or rollback,** the gate runs `git pull --ff-only` on this
  repository, so compose and tool changes merged to `main` arrive first. A
  new required setting still needs a person: `make sync-env`, fill it in.
- **Locking:** one deploy at a time; others wait, up to 30 minutes.
- **State** lives in `deploy/state/` (not in git):
  - the history per unit and `releases.log`;
  - the last 5 backups per database;
  - the data saved by resets, kept until the unit's next minor;
  - the login theme copied out of the running Keycloak image.
- **Images:** the server keeps the newest 5 tags of each image. Docker Hub
  keeps all of them.
- **First deploy:** a unit's first deploy records what runs now as its first
  history entry, so a rollback can return to it.

## Releasing, step by step

```bash
# in the service repository, on the branch from the table above
git pull
git tag v0.1.0-alpha04          # next alpha; v0.1.1-alpha00 to reset
git push origin v0.1.0-alpha04
```

Then watch the run in that repository's Actions tab. Green: deployed and
healthy. Red at "Deploy": the server is back on the previous tag, and the
log says why.

## Changing the pipelines

| What | Where |
|---|---|
| How images are built | `deploy/Makefile` (`build_*`), used by both CI (`deploy/ci/build.sh`) and laptops |
| Units, their images, services, data and cascades | `deploy/lib/units.sh` |
| Deploy, rollback, health checks, resets | `deploy/bin/kulpay` |
| The shared workflow | `.github/workflows/service.yml` |
| Each repository's tests | its own `.github/workflows/release.yml` |

Callers use `service.yml@main`, so a change merged here applies to every
repository's next tag.
