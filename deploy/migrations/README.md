# Changes to existing tables

The services' code only **creates** tables (KulOffice: one entry per
table-creating function in `internal/model/migration.go`). Anything that changes
a table that already exists is a SQL file here, run against the running
database by `bin/kulpay deploy`. A fresh database (a reset, a first deploy) is
built whole by the code, so it never needs these files.

## Adding one

1. Make the change in the code (the gorm model) as usual. A fresh database gets
   it from the code.
2. Add a file for the databases that already exist:
   `migrations/<database>/YYYY-MM-DD-NN_what.sql`, for example
   `migrations/kuloffice/2026-11-12-01_orders_note.sql`.
3. Merge it to `main` here **before** pushing the service's tag. CI's deploy
   brings this repository up to date on the server first.

```sql
-- orders.note (the code's Order.Note).
ALTER TABLE orders ADD COLUMN IF NOT EXISTS note text NOT NULL DEFAULT '';
```

## How they run

- Once per database, in name order, each in one transaction together with its
  record in that database's `kit_migrations` table.
- As the database's own role (`SET ROLE kuloffice` is added for you), so the
  service keeps owning its tables.
- Right **before** the unit switches to the new tag, after its backup. The
  version still running must keep working: add first; drop or rename in a later
  file, once nothing reads the old shape.
- A file that fails keeps nothing, and the deploy stops on the current tag.
- After a reset (or on a database with no tables yet) every file is recorded
  without running: the code already built that shape.
- Write them so they can run twice (`IF NOT EXISTS`, `IF EXISTS`): a database
  restored from an older backup may meet a file again.
- Never edit a file that has run; add another. `make migrations` (or
  `bin/kulpay migrations [database]`) lists each file, run or pending.

On the dev server KulOffice also re-runs its migrations at every start
(`KULOFFICE_DEPLOYMENT=dev`, `KULOFFICE_DATABASE_MIGRATIONS_ALWAYS=true` in
`.env`), so new columns and indexes appear there without a file. They still
need one for every other database: drops, renames, NOT NULL and data fixes
need one on dev too. KulOffice refuses to start with that setting anywhere
but dev.

Release tags check it: the service's tests build the previous tag's database,
apply these files and compare it with a fresh one from the new tag. A column
the code expects and no file adds fails the tag.
