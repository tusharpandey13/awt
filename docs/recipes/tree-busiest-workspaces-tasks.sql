-- question: Which workspaces and tasks had the most agent sessions and cost this month?
-- level: L2-L3 workspace, task
-- tables: nodes, sessions, usage
-- status: real
-- param: now (ISO time; blank means the current time; the month is its first 7 characters)
-- notes: a session counts for every workspace and task above its node.
WITH RECURSIVE anc(node_id, anc_id) AS (SELECT node_id, node_id FROM nodes UNION ALL SELECT a.node_id, n.parent_id FROM anc a JOIN nodes n ON n.node_id = a.anc_id WHERE n.parent_id IS NOT NULL),
p AS (SELECT coalesce(nullif(:now, ''), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) AS now)
SELECT n.kind, n.node_id, n.name, count(DISTINCT s.session_id) AS sessions, round(sum(c.cost_usd), 4) AS cost_usd
FROM p, nodes n
JOIN anc a ON a.anc_id = n.node_id
JOIN sessions s ON s.node_id = a.node_id AND substr(s.started_at, 1, 7) = substr(p.now, 1, 7)
LEFT JOIN (SELECT session_id, sum(cost_usd) AS cost_usd FROM usage_best GROUP BY session_id) c ON c.session_id = s.session_id
WHERE n.kind IN ('workspace', 'task')
GROUP BY n.node_id
ORDER BY sessions DESC, cost_usd DESC, n.node_id;
