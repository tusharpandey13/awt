-- question: Which sessions are not joined to any node?
-- level: L5 session
-- tables: sessions
-- status: real
SELECT session_id, provider_name, cwd, started_at FROM sessions WHERE node_id IS NULL ORDER BY started_at, session_id;
