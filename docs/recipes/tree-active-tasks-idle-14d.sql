-- question: Which tasks are active with no session in 14 days?
-- level: L3 task
-- tables: nodes, sessions
-- status: real
-- param: now (ISO time; blank means the current time)
WITH RECURSIVE anc(node_id, anc_id) AS (SELECT node_id, node_id FROM nodes UNION ALL SELECT a.node_id, n.parent_id FROM anc a JOIN nodes n ON n.node_id = a.anc_id WHERE n.parent_id IS NOT NULL),
p AS (SELECT coalesce(nullif(:now, ''), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) AS now)
SELECT t.node_id, t.name, max(s.started_at) AS last_session, round(julianday(p.now) - julianday(max(s.started_at)), 1) AS days_idle
FROM p, nodes t
LEFT JOIN anc a ON a.anc_id = t.node_id
LEFT JOIN sessions s ON s.node_id = a.node_id
WHERE t.kind = 'task' AND t.status = 'active'
GROUP BY t.node_id
HAVING max(s.started_at) IS NULL OR julianday(p.now) - julianday(max(s.started_at)) > 14
ORDER BY t.node_id;
