-- Fictional parsekit/lexgen data for the recipe tests. "Now" in the tests is 2026-11-16T12:00:00Z.
-- Loaded into a store.db that awt built, so the tables are awt's own.
DELETE FROM usage; DELETE FROM permissions; DELETE FROM effects; DELETE FROM records; DELETE FROM tool_calls; DELETE FROM messages; DELETE FROM turns;
DELETE FROM sessions; DELETE FROM nodes; DELETE FROM projects; DELETE FROM ingest_sources;

INSERT INTO projects(project_id, node_id, name, project_key, kind, created_at, updated_at, archived_at) VALUES
 ('unassigned', NULL, 'unassigned', NULL, NULL, NULL, NULL, NULL),
 ('proj-a', 'proj-a', 'parsekit', 'paseo:project/a', 'project', '2026-09-01T09:00:00Z', '2026-11-12T08:00:00Z', NULL),
 ('proj-b', 'proj-b', 'lexgen', 'paseo:project/b', 'project', '2026-09-10T09:00:00Z', '2026-09-20T10:00:00Z', NULL),
 ('proj-c', 'proj-c', 'oldkit', 'paseo:project/c', 'project', '2026-01-01T09:00:00Z', '2026-01-01T09:00:00Z', NULL),
 ('proj-d', 'proj-d', 'retired', 'paseo:project/d', 'project', '2026-01-01T09:00:00Z', '2026-01-01T09:00:00Z', '2026-02-01T09:00:00Z');

INSERT INTO nodes(node_id, kind, name, path, parent_id, project_id, status, goal) VALUES
 ('root', 'root', 'work', '.', NULL, 'unassigned', NULL, NULL),
 ('proj-a', 'project', 'parsekit', 'parsekit', 'root', 'proj-a', NULL, NULL),
 ('proj-b', 'project', 'lexgen', 'lexgen', 'root', 'proj-b', NULL, NULL),
 ('proj-c', 'project', 'oldkit', 'oldkit', 'root', 'proj-c', NULL, NULL),
 ('proj-d', 'project', 'retired', 'retired', 'root', 'proj-d', NULL, NULL),
 ('ws1', 'workspace', 'lexer', 'parsekit/lexer', 'proj-a', 'proj-a', NULL, NULL),
 ('ws2', 'workspace', 'docs', 'parsekit/docs', 'proj-a', 'proj-a', NULL, NULL),
 ('ws3', 'workspace', 'grammar', 'lexgen/grammar', 'proj-b', 'proj-b', NULL, NULL),
 ('ws4', 'workspace', 'scratch', 'scratch', 'root', 'unassigned', NULL, NULL),
 ('task1', 'task', 'tokenizer', 'parsekit/lexer/tokenizer', 'ws1', 'proj-a', 'active', 'add a tokenizer'),
 ('task2', 'task', 'lexer-tests', 'parsekit/lexer/lexer-tests', 'ws1', 'proj-a', 'active', 'test the lexer'),
 ('task3', 'task', 'readme', 'parsekit/docs/readme', 'ws2', 'proj-a', 'done', 'write the readme'),
 ('task4', 'task', 'rules', 'lexgen/grammar/rules', 'ws3', 'proj-b', 'active', 'port the rules'),
 ('task5', 'task', 'spike', 'scratch/spike', 'ws4', 'unassigned', 'active', 'try an idea'),
 ('ag1', 'agent', 'a1', 'parsekit/lexer/tokenizer/a1', 'task1', 'proj-a', NULL, NULL),
 ('ag2', 'agent', 'a2', 'parsekit/lexer/tokenizer/a1/a2', 'ag1', 'proj-a', NULL, NULL),
 ('ag3', 'agent', 'a3', 'parsekit/lexer/tokenizer/a1/a2/a3', 'ag2', 'proj-a', NULL, NULL),
 ('ag4', 'agent', 'a4', 'parsekit/lexer/lexer-tests/a4', 'task2', 'proj-a', NULL, NULL),
 ('ag5', 'agent', 'a5', 'lexgen/grammar/rules/a5', 'task4', 'proj-b', NULL, NULL),
 ('ag6', 'agent', 'a6', 'scratch/spike/a6', 'task5', 'unassigned', NULL, NULL);

INSERT INTO sessions(session_id, provider_name, conversation_id, node_id, join_confidence, cwd, request_model, started_at, ended_at, source, adapter) VALUES
 ('s1', 'claude_code', 'c1', 'ag1', 'cwd', '/work/parsekit', 'claude-a', '2026-11-03T09:00:00Z', '2026-11-03T10:00:00Z', 'claude', 1),
 ('s2', 'pi', 'c2', 'ag2', 'cwd', '/work/parsekit', 'pi-a', '2026-11-04T09:00:00Z', '2026-11-04T09:30:00Z', 'pi', 1),
 ('s3', 'opencode', 'c3', 'ag3', 'cwd', '/work/parsekit', 'oc-a', '2026-11-10T14:00:00Z', '2026-11-10T14:20:00Z', 'opencode', 1),
 ('s4', 'claude_code', 'c4', 'ag4', 'cwd', '/work/parsekit', 'claude-b', '2026-11-12T08:00:00Z', '2026-11-12T08:40:00Z', 'claude', 1),
 ('s5', 'claude_code', 'c5', 'ag5', 'cwd', '/work/lexgen', 'claude-a', '2026-09-20T10:00:00Z', '2026-09-20T10:30:00Z', 'claude', 1),
 ('s6', 'claude_code', 'c6', 'ag6', 'cwd', '/work/scratch', 'claude-a', '2026-11-15T07:00:00Z', '2026-11-15T07:10:00Z', 'claude', 1),
 ('s7', 'claude_code', 'c7', NULL, NULL, '/work/elsewhere', 'claude-a', '2026-11-14T16:00:00Z', '2026-11-14T16:05:00Z', 'claude', 1);

INSERT INTO ingest_sources(source, path, inode, offset, adapter, last_run, errors) VALUES
 ('claude', '-work-parsekit/s1.jsonl', 1, 100, 1, '2026-11-16T11:00:00Z', 0),
 ('claude', '-work-parsekit/s4.jsonl', 2, 100, 1, '2026-11-16T11:00:00Z', 0),
 ('claude', '-work-lexgen/s5.jsonl', 3, 100, 1, '2026-10-18T09:00:00Z', 0),
 ('claude', '-work-scratch/s6.jsonl', 4, 100, 1, '2026-11-16T11:00:00Z', 0),
 ('claude', '-work-elsewhere/s7.jsonl', 5, 100, 1, '2026-11-16T11:00:00Z', 0);

INSERT INTO turns(turn_id, session_id, seq, started_at, ended_at, outcome, paseo_turn, request_model, response_model) VALUES
 ('s1:0', 's1', 0, '2026-11-03T09:00:00Z', '2026-11-03T09:10:00Z', 'completed', 1, 'claude-a', 'claude-a'),
 ('s1:1', 's1', 1, '2026-11-03T09:20:00Z', '2026-11-03T09:30:00Z', 'failed', 1, 'claude-a', 'claude-a'),
 ('s1:2', 's1', 2, '2026-11-03T09:40:00Z', '2026-11-03T09:50:00Z', 'completed', 1, 'claude-a', 'claude-b'),
 ('s2:0', 's2', 0, '2026-11-04T09:00:00Z', '2026-11-04T09:10:00Z', 'completed', 1, 'pi-a', 'pi-a'),
 ('s2:1', 's2', 1, '2026-11-04T09:15:00Z', '2026-11-04T09:25:00Z', 'canceled', 1, 'pi-a', 'pi-a'),
 ('s3:0', 's3', 0, '2026-11-10T14:00:00Z', '2026-11-10T14:20:00Z', NULL, 0, 'oc-a', 'oc-a'),
 ('s4:0', 's4', 0, '2026-11-12T08:00:00Z', '2026-11-12T08:40:00Z', 'completed', 1, 'claude-b', 'claude-b'),
 ('s5:0', 's5', 0, '2026-09-20T10:00:00Z', '2026-09-20T10:30:00Z', 'completed', 1, 'claude-a', 'claude-a'),
 ('s6:0', 's6', 0, '2026-11-15T07:00:00Z', '2026-11-15T07:10:00Z', 'failed', 1, 'claude-a', 'claude-a'),
 ('s7:0', 's7', 0, '2026-11-14T16:00:00Z', '2026-11-14T16:05:00Z', 'completed', 1, 'claude-a', 'claude-a');

INSERT INTO messages(message_id, turn_id, session_id, seq, role, ts, text, parent_id, response_finish_reasons, response_model) VALUES
 ('m1', 's1:0', 's1', 1, 'user', '2026-11-03T09:00:00Z', 'fix the lexer test', NULL, NULL, NULL),
 ('m2', 's1:0', 's1', 2, 'assistant', '2026-11-03T09:00:02Z', 'looking', 'm1', '["tool_use"]', 'claude-a'),
 ('m3', 's1:1', 's1', 3, 'user', '2026-11-03T09:20:00Z', 'Fix the lexer test ', 'm2', NULL, NULL),
 ('m4', 's1:1', 's1', 4, 'assistant', '2026-11-03T09:20:04Z', 'trying again', 'm3', '["end_turn"]', 'claude-a'),
 ('m5', 's1:2', 's1', 5, 'user', '2026-11-03T09:40:00Z', 'add docs', 'm4', NULL, NULL),
 ('m6', 's1:2', 's1', 6, 'assistant', '2026-11-03T09:40:03Z', 'done', 'm5', '["end_turn"]', 'claude-b'),
 ('m7', 's2:0', 's2', 1, 'user', '2026-11-04T09:00:00Z', 'summarize the tokenizer', NULL, NULL, NULL),
 ('m8', 's2:0', 's2', 2, 'assistant', '2026-11-04T09:00:02Z', 'summary', 'm7', '["stop"]', 'pi-a'),
 ('m9', 's2:1', 's2', 3, 'user', '2026-11-04T09:15:00Z', 'now the parser', 'm8', NULL, NULL),
 ('m10', 's2:1', 's2', 4, 'assistant', '2026-11-04T09:15:01Z', 'parser', 'm9', '["stop"]', 'pi-a'),
 ('m11', 's3:0', 's3', 1, 'user', '2026-11-10T14:00:00Z', 'list the rules', NULL, NULL, NULL),
 ('m12', 's3:0', 's3', 2, 'assistant', '2026-11-10T14:00:01Z', 'rules', 'm11', '["stop"]', 'oc-a'),
 ('m13', 's4:0', 's4', 1, 'user', '2026-11-12T08:00:00Z', 'run the lexer tests', NULL, NULL, NULL),
 ('m14', 's4:0', 's4', 2, 'assistant', '2026-11-12T08:00:05Z', 'ran', 'm13', '["end_turn"]', 'claude-b'),
 ('m16', 's7:0', 's7', 2, 'assistant', '2026-11-14T16:00:01Z', 'ok', NULL, '["end_turn"]', 'claude-a'),
 ('m18', 's6:0', 's6', 2, 'assistant', '2026-11-15T07:00:01Z', 'failed', NULL, '["end_turn"]', 'claude-a'),
 ('m20', 's5:0', 's5', 2, 'assistant', '2026-09-20T10:00:06Z', 'ok', NULL, '["end_turn"]', 'claude-a');

INSERT INTO tool_calls(tool_call_id, message_id, session_id, tool_name, args, is_error, started_at, ended_at) VALUES
 ('tc1', 'm2', 's1', 'Read', '{"file_path":"lexer.py"}', 0, '2026-11-03T09:00:02Z', '2026-11-03T09:00:03Z'),
 ('tc2', 'm2', 's1', 'Read', '{"file_path":"missing.py"}', 1, '2026-11-03T09:00:02Z', '2026-11-03T09:00:03Z'),
 ('tc3', 'm4', 's1', 'Bash', '{"command":"pytest"}', 0, '2026-11-03T09:20:04Z', '2026-11-03T09:20:30Z'),
 ('tc4', 'm6', 's1', 'Bash', '{"command":"git push origin feat/lexer"}', 0, '2026-11-03T09:40:03Z', '2026-11-03T09:40:10Z'),
 ('tc5', 'm14', 's4', 'Bash', '{"command":"git push origin main"}', 0, '2026-11-12T08:00:05Z', '2026-11-12T08:00:09Z'),
 ('tc6', 'm14', 's4', 'mcp__slack__post_message', '{"channel":"eng","text":"lexer green"}', 0, '2026-11-12T08:00:05Z', '2026-11-12T08:00:06Z'),
 ('tc7', 'm8', 's2', 'Read', '{"file_path":"../out.md"}', 0, '2026-11-04T09:00:02Z', '2026-11-04T09:00:03Z'),
 ('tc8', 'm6', 's1', 'Bash', '{"command":"awt find tokenizer"}', 0, '2026-11-03T09:40:03Z', '2026-11-03T09:40:04Z'),
 ('tc9', 'm14', 's4', 'Bash', '{"command":"awt find --like lexer"}', 0, '2026-11-12T08:00:05Z', '2026-11-12T08:00:06Z'),
 ('tc10', 'm14', 's4', 'Bash', '{"command":"curl -X POST https://example.test/hook"}', 0, '2026-11-12T08:00:05Z', '2026-11-12T08:00:07Z');

INSERT INTO usage(usage_id, grain, session_id, conversation_id, provider_name, message_id, turn_id, request_model, response_model, usage_input_tokens, usage_output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, cost_source, latency_ms) VALUES
 ('m:s1:m2', 'message', 's1', NULL, 'claude_code', 'm2', 's1:0', 'claude-a', 'claude-a', 100, 50, 900, 50, NULL, NULL, 2000),
 ('m:s1:m4', 'message', 's1', NULL, 'claude_code', 'm4', 's1:1', 'claude-a', 'claude-a', 100, 20, 0, 0, NULL, NULL, 4000),
 ('m:s1:m6', 'message', 's1', NULL, 'claude_code', 'm6', 's1:2', 'claude-a', 'claude-b', 80, 30, 400, 0, NULL, NULL, 3000),
 ('m:s2:m8', 'message', 's2', NULL, 'pi', 'm8', 's2:0', 'pi-a', 'pi-a', 10, 5, 0, 0, 0.002, 'computed', 2000),
 ('m:s2:m10', 'message', 's2', NULL, 'pi', 'm10', 's2:1', 'pi-a', 'pi-a', 8, 2, 0, 0, 0.001, 'computed', 1500),
 ('m:s3:m12', 'message', 's3', NULL, 'opencode', 'm12', 's3:0', 'oc-a', 'oc-a', 10, 5, 0, 0, 0.004, 'computed', 500),
 ('m:s4:m14', 'message', 's4', NULL, 'claude_code', 'm14', 's4:0', 'claude-b', 'claude-b', 200, 100, 1000, 100, NULL, NULL, 5000),
 ('m:s7:m16', 'message', 's7', NULL, 'claude_code', 'm16', 's7:0', 'claude-a', 'claude-a', 50, 20, 0, 0, NULL, NULL, 1000),
 ('m:s6:m18', 'message', 's6', NULL, 'claude_code', 'm18', 's6:0', 'claude-a', 'claude-a', 60, 10, 0, 0, NULL, NULL, 1000),
 ('m:s5:m20', 'message', 's5', NULL, 'claude_code', 'm20', 's5:0', 'claude-a', 'claude-a', 300, 100, 0, 0, NULL, NULL, 6000),
 ('c:claude_c1:claude-a', 'session_model', 's1', 'c1', 'claude_code', NULL, NULL, NULL, 'claude-a', 180, 70, 900, 50, 0.30, 'ccusage', NULL),
 ('c:claude_c1:claude-b', 'session_model', 's1', 'c1', 'claude_code', NULL, NULL, NULL, 'claude-b', 80, 30, 400, 0, 0.10, 'ccusage', NULL),
 ('c:claude_c5:claude-a', 'session_model', 's5', 'c5', 'claude_code', NULL, NULL, NULL, 'claude-a', 300, 100, 0, 0, 0.50, 'ccusage', NULL),
 ('c:claude_c6:claude-a', 'session_model', 's6', 'c6', 'claude_code', NULL, NULL, NULL, 'claude-a', 60, 10, 0, 0, 0.05, 'ccusage', NULL),
 ('c:claude_zz:claude-a', 'session_model', NULL, 'zz', 'claude_code', NULL, NULL, NULL, 'claude-a', 5, 5, 0, 0, 9.99, 'ccusage', NULL);

INSERT INTO permissions(request_id, session_id, agent_id, node_id, tool_name, target, decision, decided_by, ts, decided_at) VALUES
 ('pr1', 's1', 'pa1', 'ag1', 'Bash', 'pytest', 'allow', 'person', '2026-11-03T09:05:00Z', '2026-11-03T09:05:30Z'),
 ('pr2', 's1', 'pa1', 'ag1', 'Bash', 'git push', 'deny', 'person', '2026-11-03T09:06:00Z', '2026-11-03T09:08:00Z'),
 ('pr3', 's1', 'pa1', 'ag1', 'Read', 'lexer.py', 'allow', 'plugin', '2026-11-03T09:07:00Z', '2026-11-03T09:07:00Z'),
 ('pr4', 's1', 'pa1', 'ag1', 'Bash', 'make', 'unanswered', NULL, '2026-11-03T09:09:00Z', NULL),
 ('pr5', 's1', 'pa1', 'ag1', 'Edit', 'lexer.py', 'allow', 'person', '2026-11-03T09:10:00Z', '2026-11-03T09:11:00Z');

INSERT INTO effects(effect_id, node_id, target, key, state, attempt, origin, rule, begun_by, begun_at, sent_ref, tool_call_id) VALUES
 ('e1', 'ag1', 'slack:#eng', 'k1', 'sent', 1, 'declared', NULL, 'a1', '2026-11-03T09:30:00Z', 'ts-1', NULL),
 ('e2', 'ag1', 'git:origin/feat/lexer', 'k2', 'begun', 1, 'detected', 'git-push', 'a1', '2026-11-13T09:00:00Z', NULL, 'tc4'),
 ('e3', 'ag4', 'gh:pr', 'k3', 'unknown', 1, 'detected', 'gh-pr', 'a4', '2026-11-16T08:00:00Z', NULL, NULL),
 ('e4', 'ag4', 'git:origin/main', 'k4', 'sent', 2, 'detected', 'git-push', 'a4', '2026-11-12T08:00:05Z', 'abc', 'tc5'),
 ('e5', 'ag5', 'slack:#eng', 'k5', 'planned', 1, 'declared', NULL, NULL, NULL, NULL, NULL),
 ('e6', 'ag5', 'slack:#eng', 'k6', 'dropped', 1, 'declared', NULL, 'a5', '2026-09-20T10:10:00Z', NULL, NULL);

INSERT INTO records(record_id, node_id, type, ts, by, fields, session_id, origin, model, turn_id) VALUES
 ('d-1', 'ag1', 'decision', '2026-11-03T09:03:00Z', 'a1', '{"type":"decision","id":"d-1","choice":"regex lexer","why":"small"}', 's1', 'agent', 'claude-a', 's1:0'),
 ('d-2', 'ag1', 'decision', '2026-11-05T09:03:00Z', 'a1', '{"type":"decision","id":"d-2","choice":"hand-written lexer","why":"speed","supersedes":"d-1"}', NULL, 'agent', 'claude-a', NULL),
 ('d-3', 'ag4', 'decision', '2026-10-01T10:00:00Z', 'a4', '{"type":"decision","id":"d-3","choice":"pytest","why":"habit"}', NULL, 'agent', 'claude-b', NULL),
 ('d-4', 'ag4', 'decision', '2026-10-20T10:00:00Z', 'a4', '{"type":"decision","id":"d-4","choice":"unittest","why":"no deps","supersedes":"d-3"}', NULL, 'agent', 'claude-b', NULL),
 ('q-1', 'ag1', 'question', '2026-11-01T09:00:00Z', 'a1', '{"type":"question","id":"q-1","text":"which token set"}', NULL, 'agent', 'claude-a', NULL),
 ('q-2', 'ag4', 'question', '2026-11-10T10:00:00Z', 'a4', '{"type":"question","id":"q-2","text":"fixture format"}', NULL, 'agent', 'claude-b', NULL),
 ('ag4#a1', 'ag4', 'answer', '2026-11-10T16:00:00Z', 'person', '{"type":"answer","ref":"q-2","text":"json"}', NULL, 'person', 'unknown:unset', NULL),
 ('q-3', 'ag5', 'question', '2026-09-20T10:00:00Z', 'a5', '{"type":"question","id":"q-3","text":"which grammar"}', NULL, 'agent', 'claude-a', NULL),
 ('ag5#a1', 'ag5', 'answer', '2026-09-21T10:00:00Z', 'person', '{"type":"answer","ref":"q-3","text":"peg"}', NULL, 'person', 'unknown:unset', NULL),
 ('q-4', 'ag5', 'question', '2026-09-20T12:00:00Z', 'a5', '{"type":"question","id":"q-4","text":"which parser"}', NULL, 'agent', 'claude-a', NULL),
 ('ag5#a2', 'ag5', 'answer', '2026-09-21T00:00:00Z', 'person', '{"type":"answer","ref":"q-4","text":"packrat"}', NULL, 'person', 'unknown:unset', NULL),
 ('q-5', 'ag6', 'question', '2026-11-15T08:00:00Z', 'a6', '{"type":"question","id":"q-5","text":"keep the spike"}', NULL, 'agent', 'claude-a', NULL),
 ('ag1#s1', 'ag1', 'state', '2026-11-03T09:45:00Z', 'a1', '{"type":"state","now":"lexer done","next":"docs"}', 's1', 'agent', 'claude-b', 's1:2'),
 ('ag2#s1', 'ag2', 'state', '2026-11-04T09:30:00Z', 'paseo-plugin', '{"type":"state","scope":"auto","now":"[auto] summary"}', NULL, 'plugin', 'pi-a', NULL),
 ('ag4#s1', 'ag4', 'state', '2026-11-12T08:30:00Z', 'a4', '{"type":"state","now":"tests run","next":"none"}', 's4', 'agent', 'claude-b', 's4:0'),
 ('n-1', 'ag4', 'note', '2026-11-12T08:10:00Z', 'a4', '{"type":"note","id":"n-1","text":"flaky test"}', 's4', 'agent', 'claude-b', 's4:0'),
 ('n-2', 'ag1', 'note', '2026-11-02T09:00:00Z', 'person', '{"type":"note","id":"n-2","text":"remember the spec"}', NULL, 'person', 'unknown:unset', NULL),
 ('ag6#n1', 'ag6', 'note', '2026-11-15T07:05:00Z', 'extractor', '{"type":"note","id":"n-3","text":"spike looks dead"}', 's6', 'inferred', 'unknown:unset', 's6:0');
