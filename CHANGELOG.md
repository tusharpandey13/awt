# Changelog

## Unreleased

### Added
- `find --like TEXT [--limit N]`: ranked related decisions, answers, notes, refs and states from every workspace in the tree.
- `decide` and `ask` print up to 3 `related:` records after the id line. `--related N` or `AWT_RELATED` sets the number; 0 turns it off. The lookup never fails the write and stops after 2 s.
- `list --since ISO8601 [--down] --json`: rows written since a time, for the Paseo plugin.
- Paseo plugin: a per-turn `awt.receipt` timeline line showing what was stored (`AWT_RECEIPT=0|changes`), `AWT_RELATED` forwarded to agents, and prompt lines for `find --like` and for calling `awt_resume` after compaction (Paseo has no session-hook field).
- The task `AGENTS.md` template points at `find --like`.

### Changed
- Distribution: `awt` must be a Python 3.9+ executable; the standard library is preferred, not required. It adds no dependency today.
- Paseo plugin: the handoff follow-up prompt is off by default. It showed up as a message in every chat and cost a model turn. The prompt block and the `awt_resume` brief already ask for a handoff. `AWT_NUDGE=1` turns it back on.
- Paseo plugin: after a turn without a handoff, the agent's last reply is recorded as state in scope `auto` instead. Nothing is sent to the chat. `AWT_AUTO_HANDOFF=0` turns it off.
- `resume`: the changes since the last handoff are measured from the agent's own state, not from the plugin's `auto` stand-in, so work after a real handoff stays visible.
- Tests ignore `AWT_DIR` and `AWT_BY` from the environment, so they pass when run from an agent session.

## 0.2.0 (2026-11-12)

Standalone tasks behave as before: the brief of a task with no tree around it is byte-identical to 0.1.0.

### Added
- Node tree: `awt init --kind root|workspace|task|agent` with `--name` and `--key`. Keys are unique across the tree, and `init --key` reuses the node that already has the key.
- `resume` in a node shows its ancestors' goals and `rule` decisions, a rollup of its children and, for an agent node, its task's state, decisions, questions and effects, all within a fixed budget.
- `list tree`; `find --up`, `--down` and `--tree` (the whole tree under the nearest root). The searches are capped at 40 hits, depth 8 and 2,000 nodes.
- `status done` is refused while descendants have open work.
- `--json` output for `list <section>` and `resume`. These keys are a contract.
- `AWT_DIR` and `AWT_BY`: agents can run anywhere and still write to their own node.
- `migrate-paseo`: a one-off, read-only importer of Paseo history from `~/.paseo` into the tree. Subagents land under their parents, and a second run changes nothing.
- Paseo plugin (`paseo-plugin/`, Paseo 0.15.4 or later):
  - One node per workspace and per agent, with subagents nested under their parent agent.
  - `AWT_DIR` set in each agent's environment, and an `awt_resume` tool.
  - A one-time handoff nudge per agent.
  - Archived agents and workspaces are marked done or paused.
  - Writes inside an agent's own node are auto-approved.

### Fixed
- `find` prefixes hits with node paths that work from the current directory: relative inside the tree, absolute otherwise.
