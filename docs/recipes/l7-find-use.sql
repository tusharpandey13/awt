-- question: How often agents run find / find --like, and whether a hit is used afterwards (phase 9 gate, step 1).
-- level: L7 tool call
-- tables: tool_calls, records
-- status: partial
-- needs: a link from a find result to a later record or file read; no phase stores it
-- notes: the counts of find calls are real (Bash commands containing 'awt find'). Whether a hit was used afterwards needs a link from a find result to a later record or file read; no phase stores it, so that column is 'needs data' and the gate cannot be decided from this.
SELECT CASE WHEN args LIKE '%--like%' THEN 'find --like' ELSE 'find' END AS verb, count(*) AS calls, count(DISTINCT session_id) AS sessions, 'needs data' AS hit_used_afterwards
FROM tool_calls WHERE tool_name = 'Bash' AND args LIKE '%awt find%' GROUP BY 1 ORDER BY 1;
