-- question: How deep do subagent chains go, and how often does a subagent's out.md get used?
-- level: L4 agent
-- tables: nodes, tool_calls
-- status: real
-- notes: chain_depth_N counts agent nodes with N agents on the way up (itself included). out_md_reads counts tool calls whose arguments name an out.md file (a read of a subagent's output).
WITH RECURSIVE d(node_id, depth) AS (
  SELECT node_id, 1 FROM nodes WHERE kind = 'agent' AND (parent_id IS NULL OR parent_id NOT IN (SELECT node_id FROM nodes WHERE kind = 'agent'))
  UNION ALL SELECT n.node_id, d.depth + 1 FROM nodes n JOIN d ON n.parent_id = d.node_id WHERE n.kind = 'agent')
SELECT 'chain_depth_' || depth AS metric, count(*) AS value FROM d GROUP BY depth
UNION ALL
SELECT 'out_md_reads', count(*) FROM tool_calls WHERE args LIKE '%out.md%'
ORDER BY metric;
