-- question: How often passive recall fires and whether the ids it showed are used afterwards, against shadow ids the agent never saw (passive recall M1 to M3, M5).
-- level: L7 record
-- tables: records, sessions, messages, tool_calls
-- status: real
-- notes: one row per recall trigger (prompt, compact, every) and result (hits, shadow, none, stopped, error). An id is used when, after its recall row, an assistant message or a tool call's arguments of a session joined to the same node, or a later record of that node (not a recall row), contains it. used / ids for result hits is M2; for shadow it is M3, how often agents find those records unaided; trigger every is M5. Passive recall helps when M2 is well above M3.
WITH r AS (SELECT rowid AS rr, node_id, ts, json_extract(fields, '$.trigger') AS trig, json_extract(fields, '$.result') AS result,
                  coalesce(json_extract(fields, '$.chars'), 0) AS chars, fields FROM records WHERE type = 'recall'),
i AS (SELECT r.rr, r.node_id, r.ts, j.value AS id FROM r, json_each(r.fields, '$.ids') j),
u AS (SELECT i.rr, i.id FROM i
      WHERE EXISTS (SELECT 1 FROM sessions s JOIN messages m ON m.session_id = s.session_id WHERE s.node_id = i.node_id AND m.role = 'assistant' AND m.ts > i.ts AND instr(m.text, i.id) > 0)
         OR EXISTS (SELECT 1 FROM sessions s JOIN tool_calls t ON t.session_id = s.session_id WHERE s.node_id = i.node_id AND t.started_at > i.ts AND instr(t.args, i.id) > 0)
         OR EXISTS (SELECT 1 FROM records x WHERE x.node_id = i.node_id AND x.type != 'recall' AND x.ts > i.ts AND instr(x.fields, i.id) > 0))
SELECT r.trig AS trigger, r.result, count(*) AS recall_rows, count(DISTINCT r.node_id) AS agents, sum(r.chars) AS chars,
       sum((SELECT count(*) FROM i WHERE i.rr = r.rr)) AS ids, sum((SELECT count(*) FROM u WHERE u.rr = r.rr)) AS used_ids
FROM r GROUP BY r.trig, r.result ORDER BY r.trig, r.result;
