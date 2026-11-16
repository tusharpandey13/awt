-- question: Sessions per provider and model per week.
-- level: L5 session
-- tables: sessions
-- status: real
-- notes: week is %Y-W%W (Monday first); model is the session's request_model.
SELECT strftime('%Y-W%W', started_at) AS week, provider_name, coalesce(request_model, '(none)') AS model, count(*) AS sessions
FROM sessions GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
