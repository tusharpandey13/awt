-- question: Turns between a user's prompt and the first record written.
-- level: L6 turn
-- tables: turns, records
-- status: real
-- notes: seconds from the turn's start to the first record joined to that turn. Turns with no record are not listed (see rec-records-per-session for who writes none). A record joins a turn only through its session id and time, so records without AWT_SESSION are missed.
SELECT t.turn_id, t.session_id, min(r.ts) AS first_record, round((julianday(min(r.ts)) - julianday(t.started_at)) * 86400) AS seconds
FROM turns t JOIN records r ON r.turn_id = t.turn_id
GROUP BY t.turn_id ORDER BY t.turn_id;
