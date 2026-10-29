# FNB pilot provisioning (bank bundle rev4)

The rev4 provisioning files work with the unchanged 2026-10-22 bank images.
They do not pull packages or contact the internet.

The installed stack is `/opt/kulpay/kulpay-stack`, with Compose and its
Makefile in `/opt/kulpay/kulpay-stack/deployment`.

1. As the account that operates the stack, create protected input and output
   directories outside the deployment tree:

       sudo install -d -m 0700 /opt/kulpay/kulpay-stack/fnb-pilot/input
       sudo install -d -m 0700 /opt/kulpay/kulpay-stack/fnb-pilot/output

   From the deployment directory, install the template and keep all KYB,
   contract and statement evidence in the same input directory:

       sudo install -m 0600 provisioning/fnb-pilot.example.yaml \
         /opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml
2. Fill every value marked `REQUIRED`. Do not change
   `deployment.gateway_profile: pilot-2026-10-22` and do not remove the
   documented `SALE/bank_transfer` compatibility row.
3. Keep credentials in the deployment `.env`, never in the YAML. Maker and
   checker must be different people and their Gateway keys must be different.
4. From `/opt/kulpay/kulpay-stack/deployment`, run:

       sudo make fnb-pilot-plan \
         PSP=/opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml \
         PSP_OUTPUT=/opt/kulpay/kulpay-stack/fnb-pilot/output

       sudo make fnb-pilot-provision \
         PSP=/opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml \
         PSP_OUTPUT=/opt/kulpay/kulpay-stack/fnb-pilot/output

5. The first apply can stop at `waiting_for_certification`. Give FNB the
   protected output directory's `statement-request.json`; place the returned
   CSV beside the YAML, set `partner.certification_statement_file`, and rerun
   the provision command.

The YAML and evidence are mounted read-only. State, reports, one-time keys,
webhook secrets and temporary passwords are written only below
`/opt/kulpay/kulpay-stack/fnb-pilot/output`, which is mode `0700`; secret
files use `0600`. The provisioner never prints secret values.

To stop a controlled pilot without deleting its audit trail:

    sudo make fnb-pilot-rollback \
      PSP=/opt/kulpay/kulpay-stack/fnb-pilot/input/fnb-pilot.yaml \
      PSP_OUTPUT=/opt/kulpay/kulpay-stack/fnb-pilot/output

See `provisioning/PILOT-2026-10-22-COMPATIBILITY.md` for the locked image source
pin, endpoint audit and known image limitations.
