# Self-hosted GitHub Actions runners

pavulla-tech's pipelines run here, on the dev server, not on GitHub's machines:
jobs on these runners use no GitHub minutes (owner, 2026-11-07). GitHub still
reads the workflows, queues the jobs, holds the secrets and shows the logs.

| Runner | Labels | Cap | Runs |
|---|---|---|---|
| `pavulla-build-1` | `self-hosted, pavulla, build` | 3 CPUs, 6 GB (its Docker engine 3 CPUs, 4 GB) | tests, image builds |
| `pavulla-build-2` | `self-hosted, pavulla, build` | 3 CPUs, 6 GB (its Docker engine 3 CPUs, 4 GB) | tests, image builds |
| `pavulla-light` | `self-hosted, pavulla, light` | 1 CPU, 1.5 GB, no Docker engine | short jobs: a release's meta step, publishing it on GitHub, submitting it to KulOffice |
| `pavulla-deploy` | `self-hosted, pavulla, deploy` | 0.5 CPU, 512 MB | deploys (SSH to the server, wait for the health check) |

- Registered once to the organisation: every pavulla-tech repo can use them.
- They give way to the server: every runner and Docker engine has a low CPU
  weight (`cpu_shares: 256`, the default is 1024), so the dev stack and the
  server's other services win when the CPU is contended. An idle server still
  gives a build its 3 CPUs.
- One job per runner at a time; more jobs wait in GitHub's queue. Deploys to the
  KulPay server also wait for each other (the `kulpay-server` concurrency group).
- Each build runner has its own Docker engine (`dind-1`, `dind-2`): a job builds
  and runs containers there, never on the server's own Docker, so it can neither
  see nor prune the stack's containers and images.
- Go's and npm's caches stay in each runner's volume between jobs; workflows do
  not use GitHub's cache.

## A workflow on these runners

```yaml
jobs:
  test:
    runs-on: [self-hosted, pavulla, build]
  deploy:
    runs-on: [self-hosted, pavulla, deploy]
```

Every job of a workflow must ask for these labels: one job on `ubuntu-latest`
cannot start when the GitHub minutes are spent, and the jobs after it wait. The
machine is not GitHub's image: a tool a job needs comes from its `setup-*` action
(`actions/setup-go`, `actions/setup-node`, …), not from what happens to be installed.

## Install (once)

On the server, as root:

```bash
cd ~/kuloffice
git pull
cd runners
cp .env.example .env && chmod 600 .env
```

Then, within the hour the token lives: GitHub → pavulla-tech → Settings →
Actions → Runners → **New self-hosted runner**, copy the token from the
`./config.sh … --token …` line, and put it in `.env` as `RUNNER_TOKEN=`.

```bash
cd ~/kuloffice/runners
docker compose up -d
docker compose logs --tail 20 build-1 build-2 deploy
```

Each log ends with `Listening for Jobs`. The three runners appear as **Idle** on
GitHub's Runners page. The token is no longer needed: empty it in `.env`.

Weekly cleanup of what the runners' Docker engines built and pulled:

```bash
cd ~/kuloffice/runners
( crontab -l 2>/dev/null; echo "30 3 * * 1 $HOME/kuloffice/runners/cleanup.sh >> /var/log/kulpay-runners-cleanup.log 2>&1" ) | crontab -
```

## Operate

- **Status:** `docker compose ps` here; GitHub's Runners page shows Idle/Active.
- **A runner stuck or Offline:** `docker compose restart build-1` (or the one named).
- **Register again** (a runner removed on GitHub, or its volume lost): a new token
  in `.env`, then `docker compose up -d --force-recreate <runner>`.
- **More parallel jobs:** copy a `build-N` + `dind-N` pair in `docker-compose.yml`
  with new names and volumes, a new token, `docker compose up -d`.
- **Disk:** `docker system df` on the server; inside an engine,
  `docker compose exec dind-1 docker system df`.

## Security

Every job's secrets reach this server while it runs: the deploy and Docker Hub
secrets of each repo, next to dev's live connector credentials. That is accepted
for the dev server because only the team pushes to pavulla-tech's private repos
and no outside pull requests run here. Never point a public repo's workflows at
these runners, and never install them on the bank's or a production server.
