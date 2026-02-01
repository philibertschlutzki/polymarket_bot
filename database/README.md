# Database Directory

This directory contains the SQLite database file: `polymarket.db`.

## Note on Git
The `polymarket.db` file is ignored by Git to prevent committing sensitive financial data and binary blobs.
However, a placeholder or test fixture might be present if explicitly added.

## Backups
It is recommended to backup this directory regularly.
```bash
cp polymarket.db polymarket.db.bak
```

## Schema
See `docs/database_schema.md` for details on tables and columns.
