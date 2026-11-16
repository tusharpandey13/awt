-- question: How much history was at risk: sessions ingested within 3 days of the Claude retention cutoff.
-- level: L5 session
-- tables: sessions, ingest_sources
-- status: real
-- param: retention_days (Claude's cleanupPeriodDays; blank means 30, the default)
-- notes: ingest_sources.last_run is the last run that touched the file, so this is the latest the session could have been ingested, not the first. Claude sessions only.
SELECT s.session_id, s.started_at, i.last_run AS last_ingest, round(julianday(i.last_run) - julianday(s.started_at), 1) AS age_days_at_ingest
FROM sessions s JOIN ingest_sources i ON i.source = 'claude' AND i.path LIKE '%/' || s.session_id || '.jsonl'
WHERE s.provider_name = 'claude_code' AND julianday(i.last_run) - julianday(s.started_at) >= coalesce(nullif(:retention_days, ''), 30) - 3
ORDER BY s.started_at, s.session_id;
