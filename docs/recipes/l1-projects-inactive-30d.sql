-- question: Projects with no activity in 30 days that are not archived.
-- level: L1 project
-- tables: projects, nodes, sessions
-- status: real
-- param: now (ISO time; blank means the current time)
-- notes: activity is a session start under the project. A project with no session at all is listed with null last_session.
WITH p AS (SELECT coalesce(nullif(:now, ''), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) AS now)
SELECT pr.project_id, pr.name, max(s.started_at) AS last_session, round(julianday(p.now) - julianday(max(s.started_at)), 1) AS days_idle
FROM projects pr CROSS JOIN p
LEFT JOIN nodes n ON n.project_id = pr.project_id
LEFT JOIN sessions s ON s.node_id = n.node_id
WHERE pr.project_id != 'unassigned' AND pr.archived_at IS NULL
GROUP BY pr.project_id
HAVING max(s.started_at) IS NULL OR julianday(p.now) - julianday(max(s.started_at)) > 30
ORDER BY pr.project_id;
