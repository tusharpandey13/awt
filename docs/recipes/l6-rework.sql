-- question: Turns after which the person re-asked the same thing (rework).
-- level: L6 turn
-- tables: messages, turns
-- status: partial
-- needs: similarity of messages in other words (phase 9 vector index); exact repeats are all awt can find
-- notes: exact repeats only: a user message whose text, trimmed and lower-cased, equals the previous user message's in the same session. A re-ask in other words is not found; that needs the phase 9 similarity data.
SELECT turn_id, session_id, text, 'needs data' AS reworded_repeats FROM (
  SELECT turn_id, session_id, seq, text, lag(lower(trim(text))) OVER (PARTITION BY session_id ORDER BY seq) AS prev
  FROM messages WHERE role = 'user' AND text != '')
WHERE lower(trim(text)) = prev ORDER BY session_id, seq;
