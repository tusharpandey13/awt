-- question: Most used tools, error rate per tool.
-- level: L7 tool call
-- tables: tool_calls
-- status: real
-- notes: errors counts is_error = 1; calls with no recorded result count as calls but not as errors.
SELECT tool_name, count(*) AS calls, coalesce(sum(is_error = 1), 0) AS errors, round(1.0 * coalesce(sum(is_error = 1), 0) / count(*), 3) AS error_rate
FROM tool_calls GROUP BY tool_name ORDER BY calls DESC, tool_name;
