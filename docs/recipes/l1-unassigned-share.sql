-- question: How much work lands in unassigned (workspaces with no project)?
-- level: L1 project
-- tables: projects, nodes, sessions
-- status: real
-- notes: nodes excludes the root. A session with no node counts as unassigned.
SELECT CASE WHEN coalesce(project_id, 'unassigned') = 'unassigned' THEN 'unassigned' ELSE 'assigned' END AS bucket, sum(is_node) AS nodes, sum(is_session) AS sessions
FROM (SELECT project_id, 1 AS is_node, 0 AS is_session FROM nodes WHERE kind != 'root'
      UNION ALL
      SELECT n.project_id, 0, 1 FROM sessions s LEFT JOIN nodes n ON n.node_id = s.node_id)
GROUP BY 1
ORDER BY 1;
