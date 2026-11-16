-- question: Session length (turns, wall time) distribution by provider.
-- level: L5 session
-- tables: sessions, turns
-- status: real
-- notes: wall time is ended_at minus started_at of the session. Min, average and max, not percentiles: the store holds few sessions per provider.
SELECT provider_name, count(*) AS sessions, round(avg(turns), 2) AS avg_turns, max(turns) AS max_turns,
       round(avg(minutes), 1) AS avg_minutes, round(min(minutes), 1) AS min_minutes, round(max(minutes), 1) AS max_minutes
FROM (SELECT s.provider_name, (SELECT count(*) FROM turns t WHERE t.session_id = s.session_id) AS turns, (julianday(s.ended_at) - julianday(s.started_at)) * 1440 AS minutes FROM sessions s)
GROUP BY provider_name ORDER BY provider_name;
