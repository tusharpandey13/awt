-- question: Cost of turns that ended failed or canceled.
-- level: L8 usage
-- tables: usage, turns
-- status: real
-- notes: from message-grain usage joined to the turn. cost_usd is null when the transcript carried no cost (Claude transcripts carry none); tokens are always shown. Only turns a Paseo turn event matched have an outcome.
SELECT t.outcome, count(DISTINCT t.turn_id) AS turns, sum(u.usage_input_tokens) AS input_tokens, sum(u.usage_output_tokens) AS output_tokens, round(sum(u.cost_usd), 4) AS cost_usd
FROM turns t JOIN usage u ON u.turn_id = t.turn_id AND u.grain = 'message'
WHERE t.outcome IN ('failed', 'canceled') GROUP BY t.outcome ORDER BY t.outcome;
