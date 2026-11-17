-- Hand-written rows for the ingested-data recipe test: what no adapter produces yet.
-- Times are fixed so the numbers can be worked out by hand. Session 3f0c1a2b-0000-4000-8000-00000000aaaa is the Claude parent session.
-- Records written by the verbs get fixed times; the first one lands in turn 1, the opening prompt (turn 0) has none.
UPDATE records SET ts = '2026-10-03T09:04:30.000Z', turn_id = '3f0c1a2b-0000-4000-8000-00000000aaaa:1' WHERE type = 'decision' AND fields LIKE '%pin the python%';
UPDATE records SET ts = '2026-10-03T09:06:00.000Z', turn_id = '3f0c1a2b-0000-4000-8000-00000000aaaa:1' WHERE type = 'decision' AND fields LIKE '%regex tokenizer%' AND fields LIKE '%use a regex%';
UPDATE records SET ts = '2026-10-10T09:06:00.000Z', turn_id = NULL WHERE type = 'decision' AND fields LIKE '%switch the lexer%';
UPDATE records SET ts = '2026-10-04T09:06:00.000Z' WHERE type = 'question' AND fields LIKE '%which regex%';
UPDATE records SET ts = '2026-10-14T09:06:00.000Z' WHERE type = 'question' AND fields LIKE '%what regex%';
-- Paseo marks turn 1 of the parent session failed (the fixture agent is not this session)
UPDATE turns SET outcome = 'failed' WHERE turn_id = '3f0c1a2b-0000-4000-8000-00000000aaaa:1';
