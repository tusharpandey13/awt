-- question: How often agents run find / find --like, and whether a hit is used afterwards (phase 9 gate, step 1).
-- level: L7 tool call
-- tables: tool_calls, records
-- status: real
-- notes: a find call is a Bash tool call whose command contains 'awt find'. Its hits are the leading path or record id of each line of its result_excerpt (the first 4 KB of the output; a path:line:, an event:ID: or an ID: prefix). A hit is used when a later tool call in the same session has the path or id in its arguments, or a later record of that session names it. Only hits with a path or an id shape count. Records join a session only with AWT_SESSION set.
WITH RECURSIVE f AS (SELECT rowid AS rid, session_id, started_at, CASE WHEN args LIKE '%--like%' THEN 'find --like' ELSE 'find' END AS verb, result_excerpt
                     FROM tool_calls WHERE tool_name = 'Bash' AND args LIKE '%awt find%'),
ln(rid, line, rest) AS (SELECT rid, '', coalesce(result_excerpt, '') || char(10) FROM f
                        UNION ALL SELECT rid, substr(rest, 1, instr(rest, char(10)) - 1), substr(rest, instr(rest, char(10)) + 1) FROM ln WHERE rest != ''),
k AS (SELECT rid, CASE WHEN line LIKE 'event:%' THEN substr(line, 7) ELSE line END AS l FROM ln WHERE line != ''),
hit AS (SELECT DISTINCT rid, substr(l, 1, instr(l || ':', ':') - 1) AS key FROM k),
hk AS (SELECT rid, key FROM hit WHERE length(key) >= 4 AND (key LIKE '%/%' OR key LIKE '%.%' OR key GLOB '[a-z]-[0-9a-f]*') AND key NOT LIKE '% %'),
used AS (SELECT DISTINCT hk.rid FROM hk JOIN f ON f.rid = hk.rid
         WHERE EXISTS (SELECT 1 FROM tool_calls t WHERE t.session_id = f.session_id AND t.started_at > f.started_at AND t.rowid != f.rid AND t.args NOT LIKE '%awt find%' AND instr(t.args, hk.key) > 0)
            OR EXISTS (SELECT 1 FROM records r WHERE r.session_id = f.session_id AND r.ts > f.started_at AND instr(r.fields, hk.key) > 0))
SELECT f.verb, count(DISTINCT f.rid) AS calls, count(DISTINCT f.session_id) AS sessions, count(DISTINCT hk.rid) AS calls_with_hits, count(DISTINCT used.rid) AS calls_with_a_used_hit
FROM f LEFT JOIN hk ON hk.rid = f.rid LEFT JOIN used ON used.rid = f.rid GROUP BY f.verb ORDER BY f.verb;
