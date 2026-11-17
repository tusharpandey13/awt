# Concepts

What the words mean. An agent needs almost none of this: it reads `BRIEF.md`, runs `awt decide` and `awt ask`, and everything else is recorded for it. This page is for the person who runs agents, reads the data, or changes the tool. Every verb is in the [reference](reference/index.md).

## The tree

A **node** is a directory with `.awt/` in it. Nodes nest:

- **root**: the top of a tree. Holds the shared contract (`AGENTS.md`).
- **project**: groups the workspaces of one repository or product. Optional.
- **workspace**: a long-lived area of work, such as one repository.
- **task**: one piece of work with a goal and a statement of what done means.
- **agent**: one chat or subagent. It has its own log and a `BRIEF.md`.

A node's parent is the nearest enclosing node. `resume` shows a node's own state plus its ancestors' goals and `rule` decisions. A single directory with `awt init` and no `--kind` is just a task with no tree around it. Details: [SPEC.md](../SPEC.md#node-tree).

## Records

A **record** is one line in a node's `.awt/events.jsonl`: a decision, question, answer, note, link, handoff (`state`), status change or effect step. Records are only appended, never rewritten, and each one names who wrote it (`by`) and the model that produced it (`model`). Never edit `.awt/` by hand; the verbs validate and scan for secrets first. Ids look like `d-7f3a9c21` (decision), `q-` (question), `e-` (effect), `n-` (note).

## BRIEF.md

Each node holds a plain file, `BRIEF.md`: the `resume` brief, kept up to date after every write. It is a view, safe to delete, never committed. An agent needs only `cat`.

## The store and store.db

The node logs say what happened in the task. The **store** holds what the agent tools saw: full session transcripts, copied by `awt ingest` from Claude Code, pi, opencode and Paseo (and usage totals from ccusage). It lives outside the tree at `${AWT_STORE:-~/.local/share/awt-store}`, because it holds whole conversations. Everything in it is private to you (mode 700/600).

`store.db` is a SQLite file built from the store and the node logs. It joins sessions, turns, messages, tool calls and cost to the projects, tasks and agents they belong to. It is derived: delete it, or run `awt ingest --rebuild`, and it comes back. The tables are in [schema.md](schema.md); ready-made queries are in [recipes/](recipes/). `awt ui` opens it read-only in a browser (needs `datasette`).

## Effects

An **effect** is something sent outside the task: a Slack message, a PR comment, a push. The ledger lets a send be made once. The tool never runs the send; it only records it.

- **Declared:** the sender writes `effect plan`, `effect begin`, sends with their own tools, then `effect mark sent`. A `begun` effect is never retried: it may have gone out.
- **Detected:** the host reports tool calls (Claude Code hooks, the Paseo plugin) and the tool labels the ones that look outbound, such as `git push`, `gh pr comment`, `curl -X POST`. The agent does nothing. This is labelling, not a permission system: it never blocks a call, and for the risky kinds, a repeat of an exact send that already went out makes the host ask the person first.

Both kinds are the same rows. Detected ones carry `origin: detected` and the `rule` that matched.

## Model tracking

Every record names its model. `--model ID` wins, then `AWT_MODEL`, then `unknown:unset`. Old rows read as `unknown:legacy`. A person (`--by person`) ignores `AWT_MODEL`. The Paseo plugin sets it for every agent, so agents do nothing. In `store.db`, `records.model` and the per-message response model let you compare cost and outcomes across models.

## Context after a compaction

When a chat is compacted, the task record should reach the agent without a message from anyone. A person (never an agent) runs `awt init --hooks claude|codex|opencode|pi|all` once per provider on the agent machine; it edits that provider's own config, so ask first. `awt init --hooks PROVIDER --uninstall` removes it. `awt doctor` warns for a provider that is present without the hook. The Paseo plugin's own message after a compaction is off unless `AWT_COMPACT_BRIEF=1`.

## Upgrading the store

`store.db` has a schema number (now 7). Install the new `awt` everywhere first (`command -v awt`, and the awt the Paseo plugin runs), update the Paseo plugin, then run `awt ingest --rebuild` once by hand. Until then hooks leave the old file alone, `doctor` warns, and `awt ui` refuses. A copy of `awt` that finds a newer schema than it knows never writes it and says to install the newer one. `awt ui` reads the live `store.db` read-only; restart it after a rebuild. `awt doctor` outside a task root runs the machine-wide checks and exits 0.

## Ingest sources and privacy

`awt ingest --source claude|pi|opencode|paseo|ccusage|all` reads each tool's own files read-only and appends them to the store. A missing source is zero rows, not an error. Nothing is sent anywhere; it makes no network calls (`awt ui` listens on `127.0.0.1` only).

Transcripts are stored whole, secrets included, because they are your own data on your own disk. Keep the store out of git and cloud-synced folders. The task tree is different: it holds only what was recorded through the verbs, and `awt doctor --staged` scans a commit for secret patterns before you share it. Claude Code deletes its transcripts after 30 days by default, so ingest regularly (the `.claude/settings.json` that `init` writes ingests at every session end) and raise `cleanupPeriodDays` if you want longer.
