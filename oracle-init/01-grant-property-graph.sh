#!/bin/bash
# Grants the one privilege the gvenzl/oracle-free image's own APP_USER/
# APP_USER_PASSWORD auto-created schema user does NOT get by default:
# CREATE PROPERTY GRAPH -- needed for
# migrations_oracle/graph_schema.sql's `CREATE PROPERTY GRAPH
# aryx_knowledge_graph ...` DDL and, downstream, oracle_graph_reader_
# traverse.py's shortest_path() SQL/PGQ query.
#
# A plain .sql file here can't reference $APP_USER (mounted files run
# via SQL*Plus with no env-var substitution) -- this needs a shell
# script so the actual runtime username is available. Runs once, on
# first boot, same as any other file in
# /container-entrypoint-initdb.d/ (gvenzl image convention).
#
# Live-untested at plan time -- the actual grant statement and
# connection shape need confirming against a real first boot (this
# plan's own stated acceptance criterion), not assumed correct here.
set -euo pipefail

sqlplus -s "sys/${ORACLE_PASSWORD}@localhost:1521/${ORACLE_DATABASE:-FREEPDB1}" as sysdba <<SQL
WHENEVER SQLERROR EXIT SQL.SQLCODE
GRANT CREATE PROPERTY GRAPH TO ${APP_USER};
EXIT;
SQL
