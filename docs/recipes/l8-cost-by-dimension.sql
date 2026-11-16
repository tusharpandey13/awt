-- question: Cost per task, per workspace, per provider and model, per day.
-- level: L8 usage
-- tables: usage, sessions, nodes
-- status: real
-- notes: one row per (dimension, key). cost_usd is usage_best summed; a dimension's keys overlap other dimensions (the same session counts in each), so never add rows across dimensions. day is the session's start day. Sessions with no cost anywhere add nothing, so a key's cost is a floor.
WITH RECURSIVE anc(node_id, anc_id) AS (SELECT node_id, node_id FROM nodes UNION ALL SELECT a.node_id, n.parent_id FROM anc a JOIN nodes n ON n.node_id = a.anc_id WHERE n.parent_id IS NOT NULL),
b AS (SELECT s.session_id, s.node_id, s.provider_name, substr(s.started_at, 1, 10) AS day, u.response_model, u.cost_usd FROM sessions s JOIN usage_best u ON u.session_id = s.session_id)
SELECT 'task' AS dimension, n.node_id AS key, round(sum(b.cost_usd), 4) AS cost_usd FROM b JOIN anc a ON a.node_id = b.node_id JOIN nodes n ON n.node_id = a.anc_id AND n.kind = 'task' GROUP BY n.node_id
UNION ALL
SELECT 'workspace', n.node_id, round(sum(b.cost_usd), 4) FROM b JOIN anc a ON a.node_id = b.node_id JOIN nodes n ON n.node_id = a.anc_id AND n.kind = 'workspace' GROUP BY n.node_id
UNION ALL
SELECT 'provider', provider_name, round(sum(cost_usd), 4) FROM b GROUP BY provider_name
UNION ALL
SELECT 'model', coalesce(response_model, '(none)'), round(sum(cost_usd), 4) FROM b GROUP BY response_model
UNION ALL
SELECT 'day', day, round(sum(cost_usd), 4) FROM b GROUP BY day
ORDER BY 1, 2;
