-- kind: duckdb
-- status: tool
-- notes: not a question and not SQLite: a DuckDB recipe that exports the store to Parquet. Run it with the duckdb CLI after setting STORE to the store directory; awt itself never links DuckDB.
INSTALL sqlite;
LOAD sqlite;
ATTACH '${STORE}/store.db' AS awt (TYPE sqlite, READ_ONLY);
COPY (SELECT * FROM awt.usage) TO 'usage.parquet' (FORMAT parquet);
COPY (SELECT * FROM awt.sessions) TO 'sessions.parquet' (FORMAT parquet);
COPY (SELECT * FROM awt.turns) TO 'turns.parquet' (FORMAT parquet);
COPY (SELECT * FROM awt.messages) TO 'messages.parquet' (FORMAT parquet);
COPY (SELECT * FROM awt.tool_calls) TO 'tool_calls.parquet' (FORMAT parquet);
COPY (SELECT * FROM awt.records) TO 'records.parquet' (FORMAT parquet);
