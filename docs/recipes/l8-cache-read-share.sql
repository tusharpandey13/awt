-- question: Cache read share of input tokens, by model; sessions with low cache share.
-- level: L8 usage
-- tables: usage
-- status: real
-- notes: share = cache_read / (input + cache_read + cache_write), from usage_best. Sessions are listed per model when the share is under 0.5.
SELECT 'model' AS metric, coalesce(response_model, '(none)') AS key, round(1.0 * sum(coalesce(cache_read_tokens, 0)) / nullif(sum(coalesce(usage_input_tokens, 0) + coalesce(cache_read_tokens, 0) + coalesce(cache_write_tokens, 0)), 0), 3) AS cache_share
FROM usage_best GROUP BY response_model
UNION ALL
SELECT 'low_session', session_id || ' ' || coalesce(response_model, '(none)'), round(1.0 * coalesce(cache_read_tokens, 0) / nullif(coalesce(usage_input_tokens, 0) + coalesce(cache_read_tokens, 0) + coalesce(cache_write_tokens, 0), 0), 3)
FROM usage_best WHERE 1.0 * coalesce(cache_read_tokens, 0) / nullif(coalesce(usage_input_tokens, 0) + coalesce(cache_read_tokens, 0) + coalesce(cache_write_tokens, 0), 0) < 0.5
ORDER BY 1, 2;
