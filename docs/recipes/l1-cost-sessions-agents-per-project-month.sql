-- question: Cost, sessions and agents per project per month.
-- level: L1 project
-- tables: projects, nodes, sessions, usage
-- status: real
-- notes: cost_usd is the best available per session (usage_best: ccusage when imported, else the cost the transcript carried); a stale ccusage import keeps its cost as a floor (cost_source ccusage_stale); null when neither exists. Unjoined sessions count under 'unassigned'.
SELECT coalesce(n.project_id, 'unassigned') AS project_id, substr(s.started_at, 1, 7) AS month, count(DISTINCT s.session_id) AS sessions, count(DISTINCT n.node_id) AS agents,
       round(sum(c.cost_usd), 4) AS cost_usd
FROM sessions s
LEFT JOIN nodes n ON n.node_id = s.node_id
LEFT JOIN (SELECT session_id, sum(cost_usd) AS cost_usd FROM usage_best GROUP BY session_id) c ON c.session_id = s.session_id
GROUP BY 1, 2
ORDER BY 2, 1;
