-- question: Effects by state; begun or unknown older than a day.
-- level: records
-- tables: effects
-- status: real
-- param: now (ISO time; blank means the current time)
-- notes: stale_effect rows list begun or unknown effects whose begun_at is more than a day before now, with their age in hours.
WITH p AS (SELECT coalesce(nullif(:now, ''), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) AS now)
SELECT 'state' AS metric, state AS key, count(*) AS value FROM effects GROUP BY state
UNION ALL
SELECT 'stale_effect', e.effect_id, round((julianday(p.now) - julianday(e.begun_at)) * 24, 1) FROM effects e, p
WHERE e.state IN ('begun', 'unknown') AND julianday(p.now) - julianday(e.begun_at) > 1
ORDER BY 1, 2;
