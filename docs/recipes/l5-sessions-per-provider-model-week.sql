-- question: Sessions per provider and model per week.
-- level: L5 session
-- tables: sessions
-- status: real
-- notes: week_start is the Monday of the ISO week the session started in (a week never splits at New Year); model is the session's request_model.
SELECT date(started_at, 'weekday 0', '-6 days') AS week_start, provider_name, coalesce(request_model, '(none)') AS model, count(*) AS sessions
FROM sessions GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
