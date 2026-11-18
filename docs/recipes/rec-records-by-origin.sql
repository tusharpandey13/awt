-- question: Records by origin (agent, person, plugin, inferred); inferred records later confirmed or contradicted.
-- level: records
-- tables: records
-- status: partial
-- needs: the phase 8 extractor's confirm/contradict judgments (phase 8 is gated, not built)
-- notes: counts by origin are real; passive recall rows (what an agent was shown, see l7-recall-use) are not records of work and are left out. Whether an inferred record was later confirmed or contradicted needs the phase 8 extractor, which is gated and not built, so that column is 'needs data'.
SELECT origin, count(*) AS records, CASE WHEN origin = 'inferred' THEN 'needs data' END AS confirmed_or_contradicted
FROM records WHERE type != 'recall' GROUP BY origin ORDER BY origin;
