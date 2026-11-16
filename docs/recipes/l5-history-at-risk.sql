-- question: How much history was at risk: sessions ingested within 3 days of the Claude retention cutoff.
-- level: L5 session
-- tables: sessions, ingest_sources
-- status: real
-- param: retention_days (Claude's cleanupPeriodDays; blank means 30, the default)
-- notes: Claude deletes a transcript by its last modification, so the age is last_run minus the session's ended_at. ingest_sources.last_run is the last run that touched the file, so this is the latest the session could have been ingested, not the first. Subagent sessions (X.agent-Y) match their file X/subagents/agent-Y.jsonl. Claude sessions only.
SELECT s.session_id, s.ended_at, i.last_run AS last_ingest, round(julianday(i.last_run) - julianday(s.ended_at), 1) AS age_days_at_ingest
FROM sessions s JOIN ingest_sources i ON i.source = 'claude' AND '/' || i.path LIKE '%/' || replace(s.session_id, '.agent-', '/subagents/agent-') || '.jsonl'
WHERE s.provider_name = 'claude_code' AND julianday(i.last_run) - julianday(s.ended_at) >= coalesce(nullif(:retention_days, ''), 30) - 3
ORDER BY s.ended_at, s.session_id;
