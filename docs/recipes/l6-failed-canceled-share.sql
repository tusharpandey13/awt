-- question: Share of turns failed or canceled, by provider and model.
-- level: L6 turn
-- tables: turns, sessions
-- status: real
-- notes: outcome is known only for turns a Paseo turn event matched; the others count as turns but never as failed or canceled, so the share is a floor. model is the turn's response model, else its request model.
SELECT s.provider_name, coalesce(t.response_model, t.request_model, '(none)') AS model, count(*) AS turns,
       sum(t.outcome = 'failed') AS failed, sum(t.outcome = 'canceled') AS canceled, sum(t.outcome IS NULL) AS outcome_unknown,
       round(1.0 * sum(t.outcome IN ('failed', 'canceled')) / count(*), 3) AS share
FROM turns t JOIN sessions s ON s.session_id = t.session_id
GROUP BY 1, 2 ORDER BY 1, 2;
