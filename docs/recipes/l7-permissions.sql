-- question: Permission requests by tool and outcome; how many waited on a person, and for how long.
-- level: L7 permission
-- tables: permissions
-- status: real
-- notes: a person's wait is decided_at minus ts of requests decided_by person. The store holds allow, deny and unanswered; it does not record ask.
SELECT tool_name, decision, count(*) AS requests, sum(decided_by = 'person') AS answered_by_person,
       round(avg(CASE WHEN decided_by = 'person' THEN (julianday(decided_at) - julianday(ts)) * 86400 END), 1) AS avg_wait_seconds
FROM permissions GROUP BY tool_name, decision ORDER BY tool_name, decision;
