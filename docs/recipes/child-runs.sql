-- question: Which launching tool call, session and transcript belongs to each child node (RUN_KEY), and which RUN_KEY did each subagent row of a session launch?
-- level: L4 agent
-- tables: nodes, records, tool_calls, sessions, canonical
-- status: real
-- notes: one row per (child node, launching call). A child node is a node whose node record has `run` (awt init --child). link ref: the child's own ref row tool-call:ID, written by the launch hook, joined to tool_calls by id (session_id and tool_name are NULL when that call is not ingested). link run_key: no ref, but a call of Agent, Task or subagent in a session joined to the child's parent node whose input holds a line `RUN_KEY: <run_key>` (a launch whose hook was not installed; any line of any field counts here, not only the first five). child_session_id: for a Claude subagent the session `<session>.agent-<agentId>` of the call's result (toolUseResult.agentId); NULL for pi and for a call without a result. Join sessions.node_id to this recipe's session_id to see the RUN_KEY of every row an ingested Paseo session launched. No schema change: everything here is read from the existing tables.
WITH child AS (
  SELECT n.node_id, n.parent_id, json_extract(r.fields, '$.run') AS run_key
  FROM records r JOIN nodes n ON n.node_id = r.node_id
  WHERE r.type = 'node' AND json_extract(r.fields, '$.run') IS NOT NULL),
by_ref AS (
  SELECT c.node_id, c.run_key, substr(json_extract(r.fields, '$.target'), 11) AS tool_call_id
  FROM child c JOIN records r ON r.node_id = c.node_id AND r.type = 'ref' AND json_extract(r.fields, '$.target') LIKE 'tool-call:%'),
by_key AS (
  SELECT DISTINCT c.node_id, c.run_key, t.tool_call_id
  FROM child c
  JOIN sessions s ON s.node_id = c.parent_id
  JOIN tool_calls t ON t.session_id = s.session_id AND t.tool_name IN ('Agent', 'Task', 'subagent')
  WHERE instr(char(10) || replace(replace(t.args, '\n', char(10)), '"', char(10)) || char(10), char(10) || 'RUN_KEY: ' || c.run_key || char(10)) > 0
    AND NOT EXISTS (SELECT 1 FROM by_ref x WHERE x.node_id = c.node_id AND x.tool_call_id = t.tool_call_id)),
link AS (
  SELECT node_id, run_key, tool_call_id, 'ref' AS link FROM by_ref
  UNION ALL SELECT node_id, run_key, tool_call_id, 'run_key' FROM by_key),
agent AS (
  SELECT json_extract(b.value, '$.tool_use_id') AS tool_call_id, json_extract(c.raw, '$.toolUseResult.agentId') AS agent_id
  FROM canonical c, json_each(c.raw, '$.message.content') b
  WHERE c.src = 'claude' AND json_extract(c.raw, '$.toolUseResult.agentId') IS NOT NULL AND json_type(c.raw, '$.message.content') = 'array'
    AND json_extract(b.value, '$.type') = 'tool_result')
SELECT l.node_id, l.run_key, l.tool_call_id, t.session_id, t.tool_name, l.link,
       (SELECT s.session_id FROM agent a JOIN sessions s ON s.session_id = t.session_id || '.agent-' || a.agent_id WHERE a.tool_call_id = l.tool_call_id LIMIT 1) AS child_session_id
FROM link l LEFT JOIN tool_calls t ON t.tool_call_id = l.tool_call_id
ORDER BY l.run_key, l.tool_call_id, t.session_id;
