-- question: Turns between a user's prompt and the first record written.
-- level: L6 turn
-- tables: turns, records
-- status: real
-- notes: per session: turns is how many turns it has, first_record_turn the seq of the first turn that has a record joined to it, turns_before_first_record the turns that passed (turn 0 is the opening prompt) before it, seconds_to_first_record from the first turn's start to that record. A session with no record shows nulls (see rec-records-per-session for who writes none). A record joins a turn only through its session id and time, so records without AWT_SESSION are missed. Passive recall rows are written at the prompt by a hook and are not counted.
SELECT s.session_id, count(DISTINCT t.turn_id) AS turns, min(CASE WHEN r.record_id IS NOT NULL THEN t.seq END) AS first_record_turn,
       min(CASE WHEN r.record_id IS NOT NULL THEN t.seq END) - min(t.seq) AS turns_before_first_record,
       round((julianday(min(r.ts)) - julianday(min(t.started_at))) * 86400) AS seconds_to_first_record
FROM sessions s JOIN turns t ON t.session_id = s.session_id LEFT JOIN records r ON r.turn_id = t.turn_id AND r.type != 'recall'
GROUP BY s.session_id ORDER BY s.session_id;
