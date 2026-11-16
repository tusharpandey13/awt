# ADR 0009: origin isolation (Claude readers do not read non-Claude data)

Status: proposed, 2026-11-16. The full design and the SPEC delta are in `docs/ORIGIN-ISOLATION.md`. Process as in ARCHITECTURE-v2 section 9: two independent reviews, then the owner.

## Context

The owner's requirement (2026-11-16): a Claude reader must not read awt data whose origin is a known non-Claude model. "Claude" means the model family, whatever the harness. Person-written and legacy records stay visible, and readers from other families are unrestricted for now. Enforcement has three parts: hard isolation (split storage, plus Claude Code permission rules), filtering in every awt read, and hooks. The owner later added that the rules must be a configurable policy, which decides both the filters and where data is stored, and that agents must not be able to loosen it.

The model of every row is already recorded (Model tracking, phases 2 and 4). Several facts constrain the design:

- the store is a single directory;
- node logs live in the tree, which may be committed;
- Claude Code under Paseo does not load a node's settings;
- Claude Code permission deny rules cover its file tools and the file commands it recognises in Bash, but not arbitrary scripts (only its sandbox does);
- pi has no hooks or permission prompts that awt controls.

## Options considered

**Storage:**

| Option | For | Against |
|---|---|---|
| A. One store, filter only (a `class` column) | Smallest change | No hard isolation: `sqlite3 store.db` or `cat events.jsonl` shows everything. Fails the requirement |
| B. Two partitions, "Claude-visible" and "restricted", with data moved on every policy change | One deny rule | A policy change rewrites append-only data in both directions. Cannot express two restricted reader families |
| C. One partition per origin class, outside the tree, with the open set staying where it is today (**chosen**) | Under the default, one deny rule (`sealed/**`). Loosening moves nothing. Generic: any reader → classes map turns into deny rules and views | Tightening leaves old rows in open files until a one-off migration. One more derived database |
| D. Encrypt sealed data at rest | Hides content from tools that are not denied | Every agent runs as the owner's user and can reach the key. Complexity without a wall |

**Where the Claude Code rules live:**

| Option | Against |
|---|---|
| The node's `.claude/settings.json` | Not loaded under Paseo, and absent outside nodes |
| `~/.claude/settings.json`, merged by awt | Clobber risk in a file the owner's agents edit routinely, and those agents can remove the rules |
| A managed-settings drop-in (`managed-settings.d/50-awt-origin.json`) (**chosen**) | Needs one `sudo` by the owner |

**Reader identity:**

| Option | Against |
|---|---|
| A `--reader` flag | Any agent can pass it |
| `AWT_MODEL` alone | Standalone Claude Code sets no `AWT_MODEL` |
| Ordered signals, where any Claude signal wins and anything unclear gets the strictest view (**chosen**) | |

**Policy override for tests:**

| Option | Against |
|---|---|
| `AWT_POLICY` | An agent could set it and loosen the rules |
| `AWT_STORE` scoping only (**chosen**) | |

## Decision

1. **One classifier**, `family(model, by)`. It normalises the reported id (provider prefixes, Bedrock region and ARN forms, Vertex `@`, `[1m]`), then matches a shipped pattern table and the policy's additions. Rules for the special values:
   - `<provider>:default` resolves only through the policy's `provider_defaults`, and is otherwise `unknown`;
   - a concrete id that matches nothing is `other`, which is a known non-Claude model and therefore sealed by default.

   The patterns are data, so the plugin's TypeScript port reads the same table. One vector file is normative for both ports.
2. **Policy file** `$AWT_STORE/origin-policy.json`:
   - optional; edited only by a person; no environment override;
   - when invalid, it fails closed: each reader sees only its own family, `person` and `legacy`;
   - the shipped default is the owner's rule.
3. **Reader resolution:**
   - `CLAUDECODE` → `claude`;
   - else a concrete `AWT_MODEL` → its family;
   - else an `AWT_MODEL` that names no concrete model → `unknown`;
   - else `AWT_READER=full` (honoured only with neither of the two variables above) → person;
   - else an interactive TTY → person;
   - else `unknown`.

   `unknown` gets the strictest view. Under-showing is visible and recoverable; over-showing is not.
4. **Placement at write:**
   - a row whose class is in the open set goes where it goes today: the node's `.awt/events.jsonl`, or `log/` in the store;
   - otherwise it goes to `$AWT_STORE/sealed/<class>/`, keyed by a new `.awt/nid`;
   - `node` and `status` rows always stay in the tree (structure);
   - effect steps follow their `planned` row.

   Transcript rows are classified per row by their effective model (their own model, else carried forward), so a session that switches models splits across the two places with a global `seq`.
5. **Views:**
   - `store.db` is the open view;
   - `sealed/_views/full.db` is the full view;
   - a policy can make further views;
   - each view is built by the same code, is byte-stable, and is rebuilt when the policy hash changes;
   - `BRIEF.md` is always the open view.
6. **Claude Code enforcement:**
   - a generated managed-settings drop-in holding `Read`/`Edit` deny rules for `sealed/**`, plus `Edit` for the policy file;
   - a PreToolUse origin guard for the file tools, Bash and MCP, behind a `sh` prefilter that costs about 4 ms on a non-matching call;
   - `doctor` fails while the policy seals something from `claude` and the rules are not installed.

   The guard is the only thing awt ever denies.
7. **Reads:**
   - every verb filters by reader, and a hidden id behaves exactly like a missing one;
   - no output counts or hints at hidden rows;
   - a process never opens a path that its reader may not read, with two exceptions: the resend check (in the hook or plugin process) and the `status done` existence stat.

   Those two one-bit leaks, and the structural and raw-link leaks, are listed in the design for the owner.
8. **Policy changes move nothing.** Loosening needs no move. Tightening is filtered at once, and `migrate-origin`, a person's one-off script like `migrate-paseo`, moves the rows that are already in open files.
9. **Plugin:**
   - sets `AWT_MODEL` per agent call, and `AWT_READER=full` for its own calls;
   - denies a Claude-family agent's permission requests into `sealed/` (its only deny);
   - picks one of two static prompt blocks by the agent's class.

## Consequences

- **Hard isolation where a host gives a wall.** For Claude Code's tools and recognised commands, the managed deny rules are the wall, and they hold under Paseo too (to be verified, G2). Arbitrary scripts are stopped only by Claude Code's sandbox, which is the owner's choice to turn on. Claude models under opencode are covered by the plugin's deny where opencode asks. Under pi only filtering holds. The design says so, and the chaos tests pin the known misses.
- **New invariant:** a restricted `awt` never opens a sealed path. awt therefore works inside the sandbox, and ingest from a Claude process degrades to a per-file error that a later privileged run resolves.
- **Exceptions to earlier decisions:**
  - ADR 0003 is unchanged: `raw` is never altered, which is why raw links in mixed sessions leak existence.
  - "Detected effects are labelling, not a permission system" gains one stated exception, the origin guard.
  - Append-only node logs are rewritten only by `migrate-origin`, run by a person and reported. Git history keeps the old rows.
- **Costs:**
  - a second derived database;
  - a `class` column, which moves the schema to version 7 (a rebuild);
  - the store-wide `BRIEF.md` regeneration when the policy changes;
  - about 3,500–4,000 lines including tests;
  - one PR on top of phase 5, built after the phase 5 review fixes land.
- **Open for the owner:**
  - whether `unknown` origin is visible;
  - installing the drop-in;
  - the sandbox;
  - whether to deny the providers' own stores;
  - the two one-bit leaks;
  - the structural rows;
  - agents' own files.
