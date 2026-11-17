-- question: Open questions by age; median time to answer.
-- level: records
-- tables: records
-- status: real
-- param: now (ISO time; blank means the current time)
-- notes: open_question rows give age in days; median_hours_to_answer is one row, the lower median over answered questions (answer row ts minus question ts).
WITH p AS (SELECT coalesce(nullif(:now, ''), strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) AS now),
q AS (SELECT json_extract(q.fields, '$.id') AS qid, q.node_id, q.ts, (SELECT min(a.ts) FROM records a WHERE a.type = 'answer' AND json_extract(a.fields, '$.ref') = json_extract(q.fields, '$.id')) AS answered
      FROM records q WHERE q.type = 'question'),
h AS (SELECT (julianday(answered) - julianday(ts)) * 24 AS hrs, row_number() OVER (ORDER BY julianday(answered) - julianday(ts)) AS rk, count(*) OVER () AS n FROM q WHERE answered IS NOT NULL)
SELECT 'open_question' AS metric, q.qid || ' @ ' || q.node_id AS key, round(julianday(p.now) - julianday(q.ts), 1) AS value FROM q, p WHERE q.answered IS NULL
UNION ALL
SELECT 'median_hours_to_answer', '', round(v, 1) FROM (SELECT hrs AS v FROM h WHERE rk = (n + 1) / 2)
ORDER BY 1, 3 DESC;
