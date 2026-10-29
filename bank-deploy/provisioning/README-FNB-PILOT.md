# FNB pilot provisioning (bank bundle rev4)

The rev4 provisioning files work with the unchanged 2026-10-22 bank images.
They do not pull packages or contact the internet, and they do not need
`make`: every step below is a plain `docker compose` or `sh` command (the
Makefile targets of the same names run exactly these).

The installed stack is `/opt/kulpay/kulpay-stack`, with Compose in
`/opt/kulpay/kulpay-stack/deployment` and the reverse proxy installed as the
overlay `compose.nginx.yaml`: every Compose command names all three files.
The update leaves the deployment `Makefile` as it is (the proxy installer
edited it). Run every command from the deployment directory:

    cd /opt/kulpay/kulpay-stack/deployment

1. Back up, install the update and reload the Gateway (the update adds a
   launch matrix that enables live cash deposits through partner banks):

       sudo env COMPOSE="docker compose --env-file .env -f compose.yaml -f compose.miniailive.yaml -f compose.nginx.yaml" sh scripts/backup.sh
       sudo cp compose.yaml compose.yaml.rev3
       sudo unzip -o /path/to/kulpay-bank-pilot-2026.10.22-rev4-update.zip -d /opt/kulpay/kulpay-stack
       sudo env ENV_FILE=.env sh scripts/check-config.sh
       sudo docker compose --env-file .env -f compose.yaml -f compose.miniailive.yaml -f compose.nginx.yaml config --quiet
       sudo docker compose --env-file .env -f compose.yaml -f compose.miniailive.yaml -f compose.nginx.yaml up -d --force-recreate gateway-config gateway
       sudo env COMPOSE="docker compose --env-file .env -f compose.yaml -f compose.miniailive.yaml -f compose.nginx.yaml" sh scripts/health.sh

2. Create protected input and output directories outside the deployment
   tree, and install the template there. Keep all KYB, contract and
   statement evidence in the same input directory:

       sudo install -d -m 0700 /opt/kulpay/kulpay-stack/fnb-pilot/input
       sudo install -d -m 0700 /opt/kulpay/kulpay-stack/fnb-pilot/output
       sudo install -m 0600 provisioning/fnb-pilot.example.yaml \
         /opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml

3. Fill every value marked `REQUIRED`. Do not change
   `deployment.gateway_profile: pilot-2026-10-22` and do not remove the
   documented `SALE/bank_transfer` compatibility row.
4. Keep credentials in the deployment `.env`, never in the YAML. Maker and
   checker must be different people and their Gateway keys must be different.
5. Check (changes nothing), then provision (resumable: run it again at any
   time and it continues where it stopped):

       sudo env PSP_CONFIG=/opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml \
         PSP_OUTPUT=/opt/kulpay/kulpay-stack/fnb-pilot/output sh scripts/provision-psp.sh plan

       sudo env PSP_CONFIG=/opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml \
         PSP_OUTPUT=/opt/kulpay/kulpay-stack/fnb-pilot/output sh scripts/provision-psp.sh apply

6. Certification runs two rounds in the same apply: the second needs a
   statement listing the test payments the Gateway made in its own sandbox
   during the first, and on these images the provisioner writes it itself
   (none of those payments is FNB's). Nothing is asked of FNB. The run ends
   with `RESULT pilot_ready`.

The YAML and evidence are mounted read-only. State, reports, one-time keys,
webhook secrets and temporary passwords are written only below
`/opt/kulpay/kulpay-stack/fnb-pilot/output`, which is mode `0700`; secret
files use `0600`. The provisioner never prints secret values.

To stop a controlled pilot without deleting its audit trail:

    sudo env PSP_CONFIG=/opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml \
      PSP_OUTPUT=/opt/kulpay/kulpay-stack/fnb-pilot/output sh scripts/provision-psp.sh rollback

See `provisioning/PILOT-2026-10-22-COMPATIBILITY.md` for the locked image source
pin, endpoint audit and known image limitations.
