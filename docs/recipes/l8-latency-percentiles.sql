-- question: Time to first token and turn latency percentiles by model.
-- level: L8 usage
-- tables: usage, turns, sessions
-- status: partial
-- needs: time to first token; no provider transcript carries it
-- notes: message_latency_ms is the message's latency_ms (Claude: from the record the request answers to the reply's last record; pi: durationMs; opencode: completed minus created), nearest-rank p50 and p90 by response model. turn_seconds is the turn's wall time by its response model. Time to first token is not in any provider's transcript, so it is not computed.
WITH m AS (SELECT response_model AS model, latency_ms * 1.0 AS v, row_number() OVER (PARTITION BY response_model ORDER BY latency_ms) AS rk, count(*) OVER (PARTITION BY response_model) AS n
           FROM usage_msg WHERE latency_ms IS NOT NULL AND response_model IS NOT NULL),
t AS (SELECT coalesce(response_model, request_model) AS model, (julianday(ended_at) - julianday(started_at)) * 86400 AS v FROM turns WHERE ended_at IS NOT NULL AND coalesce(response_model, request_model) IS NOT NULL),
t2 AS (SELECT model, v, row_number() OVER (PARTITION BY model ORDER BY v) AS rk, count(*) OVER (PARTITION BY model) AS n FROM t)
SELECT 'message_latency_ms' AS metric, model, n AS samples, max(CASE WHEN rk = (n + 1) / 2 THEN v END) AS p50, max(CASE WHEN rk = (9 * n + 9) / 10 THEN v END) AS p90 FROM m GROUP BY model
UNION ALL
SELECT 'turn_seconds', model, n, round(max(CASE WHEN rk = (n + 1) / 2 THEN v END), 1), round(max(CASE WHEN rk = (9 * n + 9) / 10 THEN v END), 1) FROM t2 GROUP BY model
UNION ALL
SELECT 'ttft_ms', '(all)', 0, 'needs data', 'needs data'
ORDER BY 1, 2;
