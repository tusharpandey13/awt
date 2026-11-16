-- question: Records per session: which agents record and which do not.
-- level: records
-- tables: records, sessions
-- status: real
-- notes: a record counts for a session only when it carries a session id (AWT_SESSION, or `by` naming the session); records without one are not attributed, so a zero can be an agent that records without telling awt its session.
SELECT s.session_id, s.provider_name, s.node_id, count(r.record_id) AS records
FROM sessions s LEFT JOIN records r ON r.session_id = s.session_id
GROUP BY s.session_id ORDER BY records DESC, s.session_id;
