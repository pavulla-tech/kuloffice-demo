# FNB pilot provisioning (bank bundle rev4)

The rev4 provisioning files work with the unchanged 2026-10-22 bank images.
They do not pull packages or contact the internet.

1. Copy `fnb-pilot.example.yaml` to a protected working directory as
   `fnb-pilot.yaml`. Keep all KYB, contract and statement evidence beside it.
2. Fill every value marked `REQUIRED`. Do not change
   `deployment.gateway_profile: pilot-2026-10-22` and do not remove the
   documented `SALE/bank_transfer` compatibility row.
3. Keep credentials in the deployment `.env`, never in the YAML. Maker and
   checker must be different people and their Gateway keys must be different.
4. From `deployment/`, run:

       make fnb-pilot-plan PSP=/absolute/path/fnb-pilot.yaml
       make fnb-pilot-provision PSP=/absolute/path/fnb-pilot.yaml

5. The first apply can stop at `waiting_for_certification`. Give FNB the
   protected output directory's `statement-request.json`; place the returned
   CSV beside the YAML, set `partner.certification_statement_file`, and rerun
   the provision command.

The YAML and evidence are mounted read-only. State, reports, one-time keys,
webhook secrets and temporary passwords are written only below
`fnb-pilot-output/`, which is created with mode `0700`; secret files use
`0600`. The provisioner never prints secret values.

To stop a controlled pilot without deleting its audit trail:

    make fnb-pilot-rollback PSP=/absolute/path/fnb-pilot.yaml

See `provisioning/PILOT-2026-10-22-COMPATIBILITY.md` for the locked image source
pin, endpoint audit and known image limitations.
