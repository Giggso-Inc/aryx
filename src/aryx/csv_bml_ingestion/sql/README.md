# Generated SQL

This folder is empty by design. The first time a CSV whose table has a BML query is
ingested, an LLM agent authors `<table>/schema.sql`, `<table>/indexes.sql` and
`<table>/bml_source.md` here (validated before they are saved or executed). Review them and
commit them if you want them as the reviewed reference; later runs reuse them and never
overwrite them.

Set `ARYX_CSV_BML_SQL_DIR` to keep the generated files outside the package.
