-- question: Share of agents that use any awt verb at all; which verbs (tests the zero-abstraction principle).
-- level: L7 record
-- tables: nodes, records
-- status: real
-- notes: a verb shows as the record type it writes (decision, question, answer, note, state, ...), counted for rows written by an agent (origin agent). Verbs that write nothing (resume, find, list) are not visible here; see l7-find-use.
SELECT 'agents_total' AS metric, '' AS key, count(*) AS value FROM nodes WHERE kind = 'agent'
UNION ALL
SELECT 'agents_with_agent_records', '', count(DISTINCT r.node_id) FROM records r JOIN nodes n ON n.node_id = r.node_id WHERE n.kind = 'agent' AND r.origin = 'agent'
UNION ALL
SELECT 'verb_rows', type, count(*) FROM records WHERE origin = 'agent' GROUP BY type
ORDER BY 1, 2;
