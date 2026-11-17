-- question: Outbound-looking tool calls with no effect row (detection misses).
-- level: L7 tool call
-- tables: tool_calls, effects
-- status: real
-- notes: 'outbound-looking' is an approximation kept in this file: Bash commands naming git push, gh, curl, wget, ssh, scp or rsync, and MCP tools whose name contains send, post or create. awt's own rules (the awt script) are the reference; adjust the patterns here to match.
SELECT c.session_id, c.tool_call_id, c.tool_name, substr(c.args, 1, 80) AS args
FROM tool_calls c
WHERE ((c.tool_name = 'Bash' AND (c.args LIKE '%git push%' OR c.args LIKE '%"gh %' OR c.args LIKE '%curl %' OR c.args LIKE '%wget %' OR c.args LIKE '%ssh %' OR c.args LIKE '%scp %' OR c.args LIKE '%rsync %'))
   OR (c.tool_name LIKE 'mcp\_\_%' ESCAPE '\' AND (c.tool_name LIKE '%send%' OR c.tool_name LIKE '%post%' OR c.tool_name LIKE '%create%')))
  AND NOT EXISTS (SELECT 1 FROM effects e WHERE e.tool_call_id = c.tool_call_id)
ORDER BY c.session_id, c.tool_call_id;
