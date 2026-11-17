-- question: How many agents ended without any handoff, or only with an auto one?
-- level: L4 agent
-- tables: nodes, records
-- status: real
-- notes: a handoff is a state row of scope main (or no scope); scope auto is the plugin's stand-in.
SELECT n.node_id,
       CASE WHEN EXISTS (SELECT 1 FROM records r WHERE r.node_id = n.node_id AND r.type = 'state' AND coalesce(json_extract(r.fields, '$.scope'), 'main') != 'auto') THEN 'handoff'
            WHEN EXISTS (SELECT 1 FROM records r WHERE r.node_id = n.node_id AND r.type = 'state') THEN 'auto only'
            ELSE 'none' END AS handoff
FROM nodes n WHERE n.kind = 'agent'
ORDER BY n.node_id;
