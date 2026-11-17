-- question: Re-decisions and re-asked questions that repeat an earlier record in other words (phase 9 gate, step 2).
-- level: L7 record
-- tables: records, fts_text
-- status: partial
-- needs: a person's (or a local model's) judgment whether a candidate pair says the same thing; FTS5 matches words, not meaning
-- notes: candidate pairs only: two records of one type (decision or question) in one node, the later within 14 days of the earlier, found by an FTS5 search of the later record's words (4 letters or more) against the earlier ones, ranked by bm25 (lower is closer). Paraphrases that share no word are not found. same_meaning is 'needs data': a person reviews the pairs.
WITH RECURSIVE x AS (SELECT r.rowid AS rr, r.record_id, r.node_id, r.type, r.ts,
                            lower(CASE r.type WHEN 'decision' THEN coalesce(json_extract(r.fields, '$.choice'), '') || ' ' || coalesce(json_extract(r.fields, '$.why'), '') ELSE coalesce(json_extract(r.fields, '$.text'), '') END) AS txt
                     FROM records r WHERE r.type IN ('decision', 'question')),
w(rr, word, rest) AS (SELECT rr, '', txt || ' ' FROM x
                      UNION ALL SELECT rr, substr(rest, 1, instr(rest, ' ') - 1), ltrim(substr(rest, instr(rest, ' ') + 1)) FROM w WHERE rest != ''),
q AS (SELECT rr, '"' || group_concat(word, '" OR "') || '"' AS m FROM (SELECT DISTINCT rr, word FROM w WHERE length(word) >= 4 AND word NOT GLOB '*[^a-z0-9]*') GROUP BY rr)
SELECT a.type, a.record_id AS earlier, b.record_id AS later, a.node_id, round(julianday(b.ts) - julianday(a.ts), 1) AS days_apart, round(bm25(fts_text), 2) AS rank, 'needs data' AS same_meaning
FROM q JOIN x b ON b.rr = q.rr
JOIN fts_text ON fts_text MATCH q.m
JOIN fts_ref f ON f.id = fts_text.rowid AND f.kind = 'record'
JOIN x a ON a.rr = f.ref AND a.type = b.type AND a.node_id = b.node_id AND a.ts < b.ts AND julianday(b.ts) - julianday(a.ts) <= 14
ORDER BY a.node_id, b.ts, bm25(fts_text), a.record_id;
