-- question: Decisions superseded within 7 days (churn).
-- level: records
-- tables: records
-- status: real
-- notes: a decision row with a supersedes field replaces the decision it names; days is the gap between the two rows.
SELECT old.record_id AS superseded, new.record_id AS by_decision, round(julianday(new.ts) - julianday(old.ts), 1) AS days
FROM records new JOIN records old ON old.type = 'decision' AND json_extract(old.fields, '$.id') = json_extract(new.fields, '$.supersedes')
WHERE new.type = 'decision' AND julianday(new.ts) - julianday(old.ts) <= 7
ORDER BY old.ts, old.record_id;
