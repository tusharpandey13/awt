# ADR 0008: the project level in the node tree

Status: proposed (phase 1, part B of ARCHITECTURE-v2). Scores and process as in ARCHITECTURE-v2 section 9 still apply: two independent reviews, then the owner.

## Context

A Paseo project groups workspaces (usually the checkouts and worktrees of one repository). awt kept it only as a `ref paseo:project/<id>` on each workspace node, so there was no place to hang project-wide records and no way to list "everything for parsekit". The workspace names carried the project as a prefix (`parsekit--main`), which is a convention, not a structure.

## Decision

1. **New node kind `project`**, in a reserved directory `projects/` under the root. The tree is root > project > workspace > task > agent. A project contains only `workspace` nodes. A project is optional: a tree without one behaves as before.
2. **Legacy placement stays readable.** A `workspace` directly under the root (`workspaces/` of the root) still resolves, lists and takes tasks. `doctor` warns about it once the root also holds a project; it never fails on it. A tree that never uses projects gets no warning.
3. **Identity.** Key `paseo:project/<id>`. Name `customName ?? displayName`. A `ref` to `rootPath` (as a workspace refs its working directory) and a `ref` to its own key. A workspace with no `projectId`, and every `unassigned--*` workspace, goes under one project `unassigned`, key `paseo:project/unassigned`, with no root path.
4. **Archive.** A project with `archivedAt` becomes `done`, or `paused` when work below it is open (a workspace still active): the rule workspaces already follow. The Paseo SDK has no project archive hook and `projects.list` carries no `archivedAt` (provider audit, `docs/e2e-provider-gaps.md`), so the only source is `~/.paseo/projects/projects.json`. The plugin reads it on `workspace.archive.after` and `migrate-paseo` on every run. The path is overridable (`AWT_PASEO_PROJECTS` for the plugin, `--home` for the script) so tests use temp files. Only the archived workspace's own project is checked by the plugin, so one archive event cannot flip other projects a person reopened. awt owns the status after import; neither side ever sets `active`.
5. **Plugin.** `workspace.create.after` ensures the project node from `workspace.projectId`, then the workspace under it, so new workspaces land in place. If the project node cannot be made, the workspace goes under the root and the hook logs it: an agent keeps awt.
6. **Migration.** `migrate-paseo` reads `projects.json` (`projectId`, `displayName`, `customName`, `rootPath`, `archivedAt`), makes one project node per row (and `unassigned` when needed), and moves each workspace found directly under the root, if it is keyed `paseo:workspace/*` or `paseo:unassigned/*`, to `projects/<slug>/workspaces/` with one `rename`. The project comes from the workspace's own `ref paseo:project/<id>`, else from the snapshot or `workspaces.json`, else `unassigned`. Hand-made workspaces (no Paseo key) are not touched.

## Why moves are safe

- One `rename` per node on one filesystem moves a subtree whole, so no record is rewritten and every `.awt/events.jsonl` stays byte-identical.
- A kill leaves each node in the old place or the new one. The destination is checked first and never replaced (a taken name gets a numeric suffix). The next run finds every node by key and finishes. Chaos attack `migrate-kill-mid-move` kills the script repeatedly on a pre-project tree and compares the result with an uninterrupted run.
- Keyed refs resolve by key under the tree root first, so they follow a moved node. The plugin finds nodes by key and drops a cached path that no longer exists.
- Idempotent: a rerun finds every node by key and moves nothing.
- Hazard, accepted: a running agent's `AWT_DIR` holds the old path until it is reopened. awt exits 4 with a fix; nothing lands in the wrong node. Run the migration with the daemon stopped.

## The `projects` table (for `store.db`, phase 1 part A and later; defined here, not built)

| Column | Meaning |
|---|---|
| `project_id` | `paseo:project/<id>`, or `unassigned` |
| `node_id` | the `nodes` key of the project node (its key, else its path) |
| `name` | `customName ?? displayName` |
| `project_key` | Paseo's `projectKey` |
| `root_path` | `rootPath` |
| `kind` | Paseo's project `kind` |
| `created_at`, `updated_at` | from `projects.json` |
| `archived_at` | `archivedAt`, or null |

Grain L1. Rebuilt from node logs plus `projects.json`; nothing in it is authoritative.

## Alternatives rejected

- **Keep the project a ref.** No node, no project-wide records; the prefix convention stays fragile.
- **Warn on every root-level workspace.** A person who does not use Paseo projects would see a warning that has no remedy for them.
- **Move workspaces by copying, then delete.** Copies can half-finish and duplicate keys; a rename cannot.
- **Check every project's `archivedAt` at each archive event.** A reopened project would be flipped back by an unrelated event.

## Consequences

- `list tree`, `resume` lineage and `status done` gain one level; `K["depth"]` (8) still covers root > project > workspace > task > agent plus subagent chains.
- Older `awt` copies that do not know kind `project` quarantine nothing (the `node` row is valid JSON) but refuse the kind in `doctor`; they should be updated before a tree with projects is shared.
- `migrate-paseo` changes where it creates workspaces, so a tree made by the earlier version needs one run to be tidy; until then it still works.

## Rubric (ARCHITECTURE-v2 section 9, 0-2 each)

The author did not score this ADR when it was written. Opus review of the whole phase 1 diff (ADRs 0003 and 0008 together):

| Criterion | Author | Reviewer | Why (reviewer) |
|---|---|---|---|
| Necessity | not scored | 2 | |
| Layer fit | not scored | 2 | |
| Host-native first | not scored | 2 | |
| Buy before build | not scored | 1 | |
| Agent abstraction cost | not scored | 2 | |
| Agent ergonomics | not scored | 2 | |
| Human visibility | not scored | 1 | |
| Failure semantics | not scored | 1 | one bad record or file stopped ingest (fixed: per-file errors, doctor) |
| Data quality | not scored | 1 | src_ref line numbers were wrong after blank lines (fixed) |
| Complexity cost | not scored | 1 | |
| Honest security | not scored | 2 | |

Reviewer total 17 of 22, no zeros. The author's scores and a second independent review are still owed (section 9 steps 2 and 3).
