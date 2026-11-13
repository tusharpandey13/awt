# ADR 0007: zero abstraction cost for agents (the brief and the prompt)

Status: proposed (phase 2, brief half, of ARCHITECTURE-v2). Scores and process as in ARCHITECTURE-v2 section 9 still apply.

## Context

Agents are hurried (SPEC rule 1) and forget instructions under load. The old prompt asked an agent to call `awt_resume`, run `awt state` before stopping, remember `note`, `decide`, `ask`, `ref` and `find --like`, and know when to call resume again after compaction. About 700 chars in the plugin and about 2 KB in the task `AGENTS.md`. Each extra concept costs prompt tokens, forgetting and wrong use. Audit `docs/e2e-provider-gaps.md` also found that `awt_resume` is not delivered when Paseo's `mcp.injectIntoAgents` is false, and that Claude Code under Paseo does not load a node's `SessionStart` hook. Both delivery routes can be absent; a file cannot.

## Decision

This ADR covers the brief and the prompt. Detected effects (the host records outbound actions, so agents never declare them) come in phase 3 and get their own ADR text; nothing here depends on them, and the prompt line "everything else is recorded for you" is fully true only once phase 3 lands (sessions, turns, tool calls and handoffs are recorded already).

1. **`BRIEF.md` in every node** is the `resume` brief as a plain file, so an agent needs `cat` and nothing else. It is regenerated after `init` and after every awt write, for the node written to, its parent, and (for a task with at most 20 agents below it) those agents, which are the briefs that show that node's data. A task with a larger fan-out would turn each write into hundreds of file writes (chaos `tree-recall-2000` caught it), so its agents refresh at their own next write or session start. It is written to `.awt/` first and renamed, so a reader never sees half a file.
2. **SPEC rule 4 is amended.** Views are still computed at read time; `BRIEF.md` is the one derived file, never read back as state, safe to delete, and its write failures never fail a verb. It carries a `Generated` line because relative ages go stale in a file.
3. **Not committed.** `BRIEF.md` is added to the `.gitignore` lines `init` writes. It changes with every write and in every checkout, and rebuilds from `.awt/events.jsonl`, the file that SPEC's git rules say to commit. Committing it would make merge conflicts out of a view.
4. **Delivery has three independent routes**, any one enough: the prompt pointer to `BRIEF.md` (works with no tool and no hook), the Paseo `awt_resume` tool, and the Claude Code `SessionStart` hook (no matcher, so it also runs after compaction; it was already in the settings template, and now also refreshes the file).
5. **The prompt shrinks to about 250 chars** in the plugin block and the `AGENTS.md` template: where the brief is, `decide`, `ask`, "everything else is recorded for you". The AGENTS template keeps the subagent line. No handoff line: the plugin's `auto` state covers a forgotten handoff (decision 15). `state` stays an optional verb; `awt help agents` documents it, and the brief ends with "Before stopping: awt state ..." when there is none.

## Consequences

- A fixture agent that never sees an awt prompt still gets the brief through the hook and finds `BRIEF.md`; tests prove both (`test_brief.py` B11, plugin P2b).
- Stale parts: ages in the file are as of its `Generated` time; an ancestor above the parent, a file dropped into `docs/`, or a git commit show up at the next write or session start. Accepted: the hook and `awt_resume` always compute fresh.
- Standalone nodes with no plugin and no ingest hook lose the explicit `ref` and `capture` rows from the template. They are in `awt help agents`, and the brief's inventory line points at `list` and `find`. Rule 6 holds: a missing record degrades visibly.
- Cost: one extra file write (a few KB) per awt write, plus one per parent and per agent below a task. No daemon, no cache that is read back.

## Rejected

- Writing `BRIEF.md` from read verbs too: a read-only filesystem or a person's `awt resume` should not write.
- Regenerating every descendant on every write: a workspace write would rewrite hundreds of files for ancestor lines nobody reads from a file.
- Committing `BRIEF.md`: see 3.
