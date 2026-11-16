-- question: Which projects have open questions or begun/unknown effects anywhere below them?
-- level: L1 project
-- tables: projects, nodes, records, effects
-- status: real
-- notes: an open question is a question row with no answer row whose ref is its id.
SELECT pr.project_id, pr.name,
       (SELECT count(*) FROM records q JOIN nodes n ON n.node_id = q.node_id
         WHERE q.type = 'question' AND n.project_id = pr.project_id
           AND NOT EXISTS (SELECT 1 FROM records a WHERE a.type = 'answer' AND json_extract(a.fields, '$.ref') = json_extract(q.fields, '$.id'))) AS open_questions,
       (SELECT count(*) FROM effects e JOIN nodes n ON n.node_id = e.node_id WHERE n.project_id = pr.project_id AND e.state IN ('begun', 'unknown')) AS stuck_effects
FROM projects pr
WHERE open_questions > 0 OR stuck_effects > 0
ORDER BY pr.project_id;
