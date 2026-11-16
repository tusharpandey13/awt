# Origin isolation: which model may read which `awt` data

Status: proposed, 2026-11-16. Design only; nothing here is built. ADR: `docs/adr/0009-claude-origin-isolation.md`. Stacks on phase 5 (`feat/v2-phase5`).

## 1. Requirement

The owner stated it on 2026-11-16, then added to it the same day:

- A Claude reader cannot access `awt` data whose origin is not Claude. Readers from other providers have no restrictions yet.
- "Claude" means the Claude model family, for both the reader and the origin, whatever the harness. That covers `claude-*`, `anthropic.claude-*`, `us.anthropic.claude-*` and the other Bedrock and Vertex ids, and the `sonnet`, `opus` and `haiku` aliases. A pi or opencode agent running a Claude model is a Claude reader. Data that a Claude model produced under pi or opencode has Claude origin.
- **Visible to a Claude reader:** Claude-origin data, records a person wrote, and legacy records that carry no model (`unknown:legacy`, and `unknown:unset` from a person). **Hidden:** only data from a known non-Claude model (GPT, deepseek, gemini and so on).
- **Enforcement:** hard isolation, filtering in awt's reads, and hooks:
  - split storage, so that non-Claude-origin data lives in files that Claude Code's permission rules deny;
  - every `awt` read verb, `BRIEF.md`, the resume brief and the `awt_resume` tool filter by reader;
  - the Claude Code hook also guards direct reads of the store files.
- **Addition: the rules are configurable.** A small policy says, for each reader family, which origin families it may read. It also says how unknown, person and legacy origins are treated, and gives per-provider defaults. The shipped default is the rule above. The policy decides both the read filters and which storage partition a write lands in. Agents must not be able to loosen it for themselves.

"`awt` data" means what `awt` writes or ingests: node log rows, `capture` files, `BRIEF.md`, the canonical store, `store.db`, the effects ledger and the Paseo pipe. Section 10 covers files that agents write with their own tools.

## 2. Terms

- **Family:** the model family that a model id belongs to, such as `claude`, `openai`, `google`, `deepseek` or `other` (section 3).
- **Origin class:** the class of a row, used by the policy. It is a family, or one of `person`, `legacy` and `unknown`.
- **Reader:** the process that `awt` prints for. Its class is a family, `person` (sees everything), or `unknown`.
- **Open set:** the origin classes that every reader in the policy may read (the intersection of the allowed sets). Under the shipped default it is `{claude, person, legacy, unknown}`.
- **Sealed:** any origin class outside the open set. Sealed data lives only under `$AWT_STORE/sealed/<class>/`.
- **View:** the set of origin classes that a reader may read. The **open view** is the open set. The **full view** is everything.

## 3. Classifier

There is one classifier, `family(model, by)`, in `awt`. Its patterns are data: the shipped table, plus any additions in the policy. The plugin gets the effective table from `awt help policy --json` and runs a TypeScript port of the same normalisation. Both ports are tested against one vector file, `tests/fixtures/model-families.json` (section 13). No other code decides a family.

### 3.1 Algorithm

```
family(model, by):
  m = lower(strip(model or ""))
  1. m == "" or m == "unknown:legacy"           -> "legacy"
  2. m starts with "unknown:"                   -> "person" if by == "person" else "unknown"
  3. m in policy.models (exact, lowercased)     -> that class
  4. m matches ^([a-z0-9_.-]+):default$         -> policy.provider_defaults[provider], else "unknown"
  5. normalise:
       s = m
       s = s minus a trailing "[...]"           (claude-sonnet-4-5[1m], sonnet[1m])
       s = text after the last "/"              (anthropic/claude-x, openrouter/deepseek/deepseek-chat, Bedrock ARN .../us.anthropic.claude-x)
       s = s minus "@..." at the end            (Vertex claude-sonnet-4@20250514)
       s = s minus ":<digits>" at the end       (Bedrock anthropic.claude-3-5-sonnet-20240620-v1:0)
       s = s minus a leading "<word>:"          (anthropic:claude-x, ft:gpt-4o-...)
       s = s minus a leading region "<r>."      r in us eu apac ap jp au ca global us-gov
       s = s minus a leading "anthropic."       (anthropic.claude-x)
  6. first family in the table whose pattern matches s  -> that family
  7. otherwise                                  -> "other"
```

A person who passes `--model` gets that model's family, not `person`. Rule 2 fires only for `unknown:*`.

### 3.2 Shipped table

The patterns are anchored at the start of `s`, case-insensitive, and use only the regex subset that Python `re` and JavaScript share: no lookbehind, no named groups, no inline flags. Order matters; the first match wins.

| Family | Pattern |
|---|---|
| `claude` | `^claude(?:$\|[-._:0-9])` and `^(?:sonnet\|opus\|haiku\|fable\|opusplan)$` |
| `openai` | `^(?:gpt\|chatgpt\|o[1-9](?:$\|-)\|codex\|text-\|davinci\|babbage\|omni-)` |
| `google` | `^(?:gemini\|gemma\|learnlm\|palm\|bison)` |
| `deepseek` | `^deepseek` |
| `meta` | `^(?:llama\|meta-llama\|codellama)` |
| `mistral` | `^(?:mistral\|mixtral\|codestral\|devstral\|magistral\|ministral\|pixtral)` |
| `xai` | `^grok` |
| `qwen` | `^(?:qwen\|qwq)` |
| `moonshot` | `^(?:kimi\|moonshot)` |
| `zhipu` | `^(?:glm\|chatglm)` |
| `amazon` | `^(?:nova\|titan)` |
| `cohere` | `^(?:command\|c4ai)` |

The bare alias `default` is not a family: Claude Code's `default` depends on the account, so it gives `other`. A harness that knows it is Claude Code writes `claude-code:default`, which resolves through `provider_defaults`.

`other` is a known non-Claude model: a concrete id that matched no pattern. The requirement hides known non-Claude models, so under the default `other` is sealed. This is also the safe direction. A new Claude id that lacks the `claude` prefix would be wrongly sealed, never wrongly shown.

### 3.3 `<provider>:default`

It is resolved through the policy's `provider_defaults` and is never guessed. Shipped values:

| Provider | Family |
|---|---|
| `claude`, `claude-code`, `claude_code`, `anthropic` | `claude` |
| `codex`, `openai` | `openai` |
| `gemini`, `google` | `google` |
| `opencode`, `pi`, `paseo`, anything else | `unknown` |

opencode and pi can run any model, so their default is `unknown`. Section 5 says how `unknown` is treated.

### 3.4 What the classifier trusts

It trusts the id that the provider reports. A gateway that serves a non-Claude model under a Claude id (the ppaa mock that maps Bedrock ids to deepseek-flash) reads as Claude. That data is then wrongly visible. The fix is to name such ids in the policy's `models` map, for example `"us.anthropic.claude-sonnet-4-5": "deepseek"` in that agent's test store. The classifier cannot detect it.

### 3.5 Vectors (minimum set, both ports)

| Input (`by` = agent unless noted) | Class |
|---|---|
| `claude-sonnet-4-5`, `claude-opus-4-1-20250805`, `claude-3-5-haiku-latest`, `claude-sonnet-4-5[1m]` | claude |
| `anthropic.claude-3-5-sonnet-20240620-v1:0`, `us.anthropic.claude-sonnet-4-5-20250929-v1:0`, `eu.anthropic.claude-…`, `global.anthropic.claude-…` | claude |
| `arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-…` | claude |
| `claude-sonnet-4@20250514`, `anthropic/claude-sonnet-4-5`, `openrouter/anthropic/claude-3.5-sonnet`, `anthropic:claude-x` | claude |
| `sonnet`, `opus`, `haiku`, `fable`, `opusplan`, `Sonnet[1m]` | claude |
| `claude-code:default`, `anthropic:default` | claude |
| `gpt-5`, `o3-mini`, `o4`, `openai/gpt-4o`, `ft:gpt-4o:org::abc`, `codex-mini-latest`, `codex:default` | openai |
| `gemini-2.5-pro`, `google/gemini-2.0-flash`, `gemini:default` | google |
| `deepseek-chat`, `openrouter/deepseek/deepseek-r1`, `deepseek-flash` | deepseek |
| `meta-llama/llama-3.1-70b`, `qwen3-coder`, `kimi-k2`, `glm-4.6`, `grok-4` | named family |
| `foo-7b`, `default`, `openrouter/auto`, `claudette-1` | other |
| `unknown:legacy`, `""` | legacy |
| `unknown:unset` with by=person | person |
| `unknown:unset` with by=agent, `pi:default`, `opencode:default`, `x:default` | unknown |

`claudette-1` checks that the separator rule stops a name that only starts with "claude".

## 4. Reader identity

### 4.1 Resolution

`awt` resolves the reader once per process. The first rule that applies wins:

1. **Claude Code:** `CLAUDECODE` is set and non-empty, so the reader is `claude`. A Claude signal always wins, even over an `AWT_MODEL` that names another family.
2. **`AWT_MODEL`:** it is set and its class is a concrete family, so the reader is that family. A Claude family gives `claude`.
3. **`AWT_MODEL` set but not concrete** (`unknown:*`, an unresolved `<provider>:default`): the reader is `unknown`.
4. **`AWT_READER=full`**, only when neither of the two variables above is set: the reader is `person`. This is for the Paseo daemon's own calls, cron jobs and scripts.
5. **An interactive person:** stdin is a TTY, `AWT_BY` is unset or `person`, and none of the variables above is set. The reader is `person`.
6. **Otherwise** the reader is `unknown`.

`--model` and `--by` never change the reader. `--model` stays a flag that only labels writes, as Model tracking defines it. A reader of class `unknown` gets the **strictest view**: the open set, which under the default is the Claude view.

### 4.2 Why the fail-safe default is "strictest"

The two possible errors cost different amounts:

- **Over-restriction** gives an agent a shorter brief. It is visible and recoverable: the agent can ask, or a person can run awt.
- **Under-restriction** shows hidden data to a Claude model. That cannot be undone.

Every ambiguous case therefore resolves to the strictest view:

- an agent with no model;
- a harness with no markers;
- a person in a pipe, which has no TTY;
- an invalid policy (section 5.4).

The person path needs a TTY for the same reason. A shell export such as `AWT_READER=full` in `.zshrc` would be inherited by every agent started from that shell. Rule 4 ignores it whenever `AWT_MODEL` or `CLAUDECODE` is set, and the Paseo plugin always sets `AWT_MODEL`.

### 4.3 Where each reader comes from

| Reader | Signal |
|---|---|
| Claude Code, standalone or under Paseo | `CLAUDECODE`, which Claude Code sets in Bash tool commands. Verify it is also set in hook processes (section 13, G1) |
| Paseo agent, any provider | `AWT_MODEL`, which the plugin sets per agent: configured at create, resolved at open |
| Plugin calls made for an agent (`awt_resume`, receipts, auto state) | The plugin sets `AWT_MODEL=<agent's current model>` in that child's env (new; today it passes only `--model`) |
| Plugin system calls (key lookup, archive status) | `AWT_READER=full` in the child env |
| `relay` and its workers | Workers are `claude -p`, so they are Claude readers through `CLAUDECODE`. `relay` runs its `awt resume --scope` with `AWT_MODEL=<unit model>` so the worker's brief matches the worker |
| A person in a terminal | TTY rule |
| A Claude model under pi or opencode **without** the plugin | Nothing marks it, so it is `unknown` and gets the strictest view. That is correct under the default, but see section 10 |

### 4.4 A Claude reader whose model is unknown

Inside Claude Code, rule 1 makes the reader `claude` whatever the model is. Elsewhere, an unknown model is the `unknown` reader and gets the strictest view. In both cases the reader sees the Claude view or less.

## 5. Policy

### 5.1 File

The policy lives at `$AWT_STORE/origin-policy.json`, mode 600. It is optional: a missing file means the shipped default, which is embedded in `awt`. `awt` never writes this file. `awt help policy` prints the default, so a person can copy it, and `awt help policy --json` prints the effective policy, with the family table merged in, for the plugin.

```json
{
  "version": 1,
  "readers": {
    "claude": ["claude", "person", "legacy", "unknown"],
    "*": "*"
  },
  "provider_defaults": {
    "claude": "claude", "claude-code": "claude", "claude_code": "claude", "anthropic": "claude",
    "codex": "openai", "openai": "openai", "gemini": "google", "google": "google"
  },
  "models": {},
  "families": []
}
```

- `readers`: maps a reader family to the list of origin classes it may read, or `"*"`. `"*"` as a key covers every family that is not listed. `person` is not a key: a person always reads everything. The `unknown` reader gets the strictest view and cannot be configured, by design (section 4.2).
- `provider_defaults`: maps a provider to a class, for `<provider>:default`.
- `models`: exact id overrides, for gateway aliases (section 3.4).
- `families`: a list of `{"name", "pattern"}` entries checked **before** the shipped table. A name matches `^[a-z][a-z0-9-]{0,30}$`; the names `person`, `legacy`, `unknown` and `full`, and names starting with `_`, are reserved.

The shipped default expresses the owner's rule: Claude readers see Claude, person, legacy and unknown; everyone else sees everything.

### 5.2 Unknown origin under the default (owner check)

`unknown` covers `unknown:unset` written by an agent and an unresolved `<provider>:default`. The requirement hides only known non-Claude models, so `unknown` is visible by default. The fail-safe alternative is one line: remove `"unknown"` from the Claude list. Section 14 asks the owner to confirm.

### 5.3 Who may change it

Only a person, by hand. Agents get the following guards:

- the policy path is under an `Edit` deny rule (section 7.1) and the Bash guard (section 7.2), so Claude Code agents cannot write it;
- **reading** it is allowed: it holds no data, and a Claude-reader `awt` must read it.

There is no `AWT_POLICY` override. An environment variable that an agent can set must never loosen the rules. Tests scope everything with `AWT_STORE`: a temporary store holds its own policy and no real data, so pointing at it loosens nothing that matters.

`doctor` warns when the file is not owned by the user, is group- or world-writable, or is a symlink.

### 5.4 Invalid or unreadable policy

Fail closed. If the file exists but cannot be parsed or validated (unknown key, bad family name, a pattern that does not compile in the shared subset, larger than 64 KB, `version` other than 1):

- every agent reader reads only its own family, `person` and `legacy`;
- writes are placed by the shipped default;
- `doctor` fails, naming the problem;
- every read prints one stderr line: `warning: origin policy invalid (see awt doctor); showing the strictest view`.

### 5.5 Changing the policy after data exists

A change never moves data by itself. Placement is decided at write time (section 8). Reads always filter by the current policy, using each row's `model` and `by`, so a row is classified again on every read.

- **Loosening** (a sealed class becomes readable by more readers, or joins the open set):
  - the rows stay under `sealed/<class>/`;
  - the readers now allowed read them there;
  - the Claude Code deny rules that `awt` generates no longer list that class (section 7.1).
  - Nothing moves.
- **Tightening** (an open class becomes hidden from some reader):
  - new writes of that class go to `sealed/<class>/`;
  - rows already in the open locations (node logs in the tree, `log/` in the store) stay there;
  - awt's reads and the view databases filter them out at once;
  - hard isolation is **incomplete** for those rows until they are moved: a `cat` of a node log still shows them;
  - `doctor` (full reader) warns with the count per class;
  - `migrate-origin` (section 11) moves them.
- **Derived state follows the policy automatically:**
  - the SHA-256 of the effective policy is stored in `schema_meta.policy_sha` of every view database, so a different hash means a rebuild;
  - the first `awt` run that sees a hash different from `$AWT_STORE/ingest/policy.sha` regenerates every `BRIEF.md` in the tree. It walks with the usual depth 8 and 2,000-node limits, under `flock` on `ingest/store.lock`, and then writes the new hash. This matters most after tightening, so that no `BRIEF.md` keeps showing rows that are now hidden.

## 6. Storage layout

### 6.1 On disk

```
$AWT_STORE/                               700
  origin-policy.json                      600  optional; person-edited (section 5)
  store.db                                600  OPEN VIEW: only open-set rows
  log/<src>/<YYYY-MM>/<session>.jsonl     600  canonical rows whose class is open (at write time)
  ingest/                                 700  offsets, locks, tree, policy.sha (no content)
  claude/50-awt-origin.json               600  generated Claude Code settings drop-in (section 7.3)
  sealed/                                 700  every byte a Claude reader may not read, under the default
    <class>/                              700  one directory per sealed origin class (deepseek, openai, other, ...)
      log/<src>/<YYYY-MM>/<session>.jsonl      canonical rows of that class
      nodes/<nid>/events.jsonl                 node log rows of that class for node <nid>
      nodes/<nid>/context/<file>.md            capture bodies written by that class
    _views/<view>.db                      600  view databases other than the open view; the full view is _views/full.db
    _spool/paseo.spool.jsonl              600  the plugin's pipe spool (moved from ingest/: it holds commands and models of every agent)
    migration-report.md                        written by migrate-origin
```

Under the default, a single deny rule covers all of this: everything a Claude reader may not read is below `sealed/`. Section 7.1 gives the general rule.

### 6.2 Node logs

The tree keeps one `.awt/events.jsonl` per node, as now. It holds the open-set rows and the structural rows (section 8.2). Sealed rows of the node go to `$AWT_STORE/sealed/<class>/nodes/<nid>/events.jsonl`. They never go into the tree, which may be committed and pushed.

`nid` is a node id stored in `.awt/nid`:

- 16 random hex characters;
- created with `O_EXCL` by `init`, or on the first sealed write to a legacy node;
- never rewritten;
- moves with the directory under `mv`;
- `cp -r` of a node duplicates it, and `doctor` warns about a `nid` used twice in the tree.

A node with no `nid` has no sealed rows.

### 6.3 Merged reads

A reader's view of a node is the tree log plus `sealed/<c>/nodes/<nid>/events.jsonl` for each sealed class `c` the reader may read. Every row is then filtered by its current class (section 5.5).

- Inside one file, file order stays canonical.
- Across files, rows merge by `ts`, then tree before sealed, then class name, then file order. "Latest" (state per scope, task, status, ref per target) means last in that merged order.
- Quarantine is counted per file. A reader sees only the counts of the files it may read.

### 6.4 Canonical transcripts and mid-session switches

Each canonical row gets a new field `model`: the **effective model** used to classify it. Its class decides the file:

- class in the open set: `log/<src>/<YYYY-MM>/<session>.jsonl`, as now;
- otherwise: `sealed/<class>/log/<src>/<YYYY-MM>/<session>.jsonl`.

A session that switches between Claude and deepseek therefore has one file in each place. `seq` stays global per session and dense across the two files. The existing dedupe ("skip rows whose seq is already present") checks both places.

The effective model of a row is:

1. its own model: Claude `message.model`, pi `message.model`, an opencode message's `modelID` or `model.modelID` (the requested model on a user message), a pi `model_change` `modelId`;
2. otherwise the effective model of the previous row in the same session (carry-forward, saved per session file in the offsets file as `last_model`);
3. otherwise the first own model that appears later in the same ingest read of that session (opencode reads a session's rows together, and a pi header is usually followed by `model_change` in the same read);
4. otherwise empty, which gives class `unknown` for a transcript row. This differs from rule 1 of section 3.1: `legacy` applies only to node-log rows written before model tracking.

Notes on this rule:

- The `<synthetic>` placeholder never counts as a model.
- The opening prompt of a turn after a switch carries the **previous** model. A person's prompt that follows a Claude turn is Claude-visible, which matches "person-written records are visible".
- The rule uses only what precedes the row, plus the same read, so a rebuild never re-places rows.
- Paseo canonical rows: agent records (join keys only) are structural and open. Pipe events take the class of the agent's model carried forward in that file: a `turn` event has `model`; a `permission` event carries the last turn's model, else the agent's `provider:default`.

### 6.5 `store.db` and the views

There is one database per distinct view that the policy defines, plus the full view. Under the default:

- `$AWT_STORE/store.db` is the **open view**, for Claude readers and `unknown` readers.
- `sealed/_views/full.db` is the **full view**, for persons and non-Claude readers.

How they are built:

- Both use the schema in `docs/schema.md`. Every table that holds content gains a `class` column: `records`, `effects`, `sessions`, `turns`, `messages`, `tool_calls`, `permissions`, `usage`, `canonical` and `fts_ref`.
- The open view is built only from inputs in the open set: tree logs, `log/`, and any `sealed/<c>/` whose class is now open.
- The full view is built from everything.
- The build is the existing code run once per view with an input filter and a row filter by current class. A session with no visible row is absent from a view.
- Each view is byte-stable on its own, and the incremental update works per view.
- When nothing is sealed (no `sealed/` directory and no hidden-class rows in open files), `full.db` is not built and full readers use `store.db`.

A reader that may read some, but not all, sealed classes needs its own view, `sealed/_views/<sorted class list>.db`. The default produces none. A policy that makes one triggers an extra build. The view a reader may use is the only one it opens.

Schema version 6 becomes 7, which means a rebuild.

### 6.6 BRIEF.md

`BRIEF.md` in every node is the **open view** brief, always. It is the same file whoever wrote last: any process can compute the open view, and a Claude-reader process never needs a sealed file to write it. There is no second file. A reader with more access gets its brief from `awt resume` or `awt_resume` (section 9), so one brief file never goes stale while the other is current.

### 6.7 Effects

Effect rows are node log rows and are placed like them (section 8). Other effect files:

- claim files (`.awt/claims/<key>.<attempt>`) hold only a hash and stay in the tree;
- the body files that an effect names are the agent's own files (section 10).

### 6.8 Modes and sync

- Directories are created with mode 700 and files with mode 600, as the store already does.
- `sealed/` is created with mode 700 even inside an existing store.
- `doctor` warns when `sealed/` or anything below it is readable by others.
- `doctor`'s existing sync, network-mount and git-tree checks cover the whole store, so `sealed/` is covered too.
- `sealed/` is never inside the tree, so the tree's git and sync status cannot carry it.

## 7. Claude Code enforcement

### 7.1 Deny rules

These are generated from the policy for the reader family `claude`, the only family with a Claude Code harness.

When `claude` may read no sealed class, which is the default:

```json
{
  "permissions": {
    "deny": [
      "Read(//<STORE>/sealed/**)",
      "Edit(//<STORE>/sealed/**)",
      "Edit(//<STORE>/origin-policy.json)"
    ]
  }
}
```

`<STORE>` is the store's real path with the leading `/` removed: the `//` anchor is Claude Code's absolute-path form.

Why these three rules cover the tools:

- Claude Code applies `Read` deny rules to Read, best-effort to Grep and Glob, and to the file commands it recognises in Bash (`cat`, `head`, `tail`, `sed`, `tee`, and `<`/`>` targets).
- `Edit` covers every built-in tool that edits files.
- `Grep(path)`, `Glob(path)` and `Write(path)` rules do not match (Claude Code docs, "Configure permissions"). So the `Read` and `Edit` forms are the right ones.
- A deny rule matches when either the requested path or the resolved target matches, so a symlink into `sealed/` is denied.

When the policy lets `claude` read some sealed classes, the generator emits one `Read` rule and one `Edit` rule per denied class directory, and per view database that is not Claude's, instead of the `sealed/**` pair.

The policy file gets only `Edit`. It must stay readable.

Do **not** add `Edit` deny rules for `.awt/` (SPEC, `.claude/settings.json` section): they would stop `awt` writing its own log under a sandbox. These rules name only store paths, which a Claude-reader `awt` never writes (section 8.4) and never reads (section 9.1).

### 7.2 PreToolUse guard

The guard is the second layer, for what the deny rules miss: an unrecognised Bash command, a glob, or a missing drop-in. There are two hook entries.

1. **File tools.** Matcher `Read|Edit|Write|MultiEdit|NotebookEdit|Grep|Glob|LS`. Command:
   ```sh
   b=$(cat); case "$b" in *sealed*|*origin-policy*) printf %s "$b" | <AWT> ingest --event --hook;; esac
   ```
   A call that does not mention either string costs the same as today's prefilter: about 4 ms, with no Python.
2. **Bash and MCP.** The existing detection prefilter gains three alternatives: `*sealed*|*origin-policy*|*CLAUDECODE*`. They are checked before the outbound list, so a guarded call always reaches Python. A non-matching call still costs about 4 ms. One `case` statement with three more patterns adds microseconds.

`ingest --event --hook` dispatches on the payload. Guard checks run first, and detection runs after them, unchanged.

**Guard rules:**

- **File tools.** Deny when `file_path`, `path`, `notebook_path` or `pattern` resolves inside `<STORE>/sealed`. Resolution: `~` expanded, relative to `cwd`, `realpath`, globs expanded with `glob.glob`. Also deny when an editing tool targets the policy file.
- **Bash.** Each segment is parsed with the detection tokenizer: `;`, `&&`, `||`, `|`, `bash -c` and the rest. Each word is expanded for `~`, `$HOME`, `${HOME}`, `$AWT_STORE`, `$XDG_DATA_HOME` and globs, then resolved against `cwd` and any leading `cd DIR`. A segment is denied when:
  - any word resolves to `<STORE>/sealed`, anything inside it, or `<STORE>` itself with a recursive tool (`cp -r`, `-R`, `-a`, `rsync`, `tar`, `zip`, `find`, `grep -r`, `rg`, `du`, `ls -R`). This covers `cat`, `sqlite3`, `grep`, `cp`, `ln -s`, `python -c 'open(...)'` and `sqlite3 sealed/_views/full.db`;
  - a word names the policy file and the command is not one of `cat`, `head`, `tail`, `less`, `wc`, `jq` (without `-i`), `grep` or `rg`, or the segment redirects to it;
  - it unsets or overrides `CLAUDECODE`: `unset CLAUDECODE`, `env -u CLAUDECODE`, `CLAUDECODE=` assignments, or `env -i` followed by `awt`.
- **MCP.** Deny when any string value in `tool_input` resolves into `sealed/` (filesystem MCP servers).

**Output:**

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"awt: that path holds records this model may not read. fix: use awt resume, awt list or awt find, which show what you may read"}}
```

The text is the same whatever the path holds, so it reveals nothing that the agent did not already name.

**Reader check:** the guard runs only when the hook's reader (section 4) is not a full reader. Inside Claude Code that is always the case.

**A deliberate exception to "labelling, not a permission system":** detected effects never block, but this guard does. It is scoped to the sealed paths and the policy file and to nothing else. `awt` still never executes anything (ADR 0002).

### 7.3 Where the rules go

**Choice:** a managed-settings drop-in that `awt` generates and a person installs once:

- `awt` writes `$AWT_STORE/claude/50-awt-origin.json`, holding the deny rules of section 7.1 and both hook entries of section 7.2, with `<AWT>` as the absolute path of `awt` at generation time;
- the person installs it into `/Library/Application Support/ClaudeCode/managed-settings.d/` on macOS, or `/etc/claude-code/managed-settings.d/` on Linux.

Why:

- **Scope:** Claude Code under Paseo does not load a node's `.claude/settings.json` (SPEC). Managed settings apply to every session in every directory, including Paseo's agents and agents started outside any node. G2 in section 13 verifies Paseo's Claude agents.
- **Agents cannot loosen it:** the directory is root-owned, and managed settings cannot be overridden by user, project or `--settings` values. Per the Claude Code docs, a mod can approve a call that a deny rule refuses in a setup without managed settings, so managed settings also close that gap.
- **No clobbering:** a drop-in is awt's own file, merged by Claude Code in alphabetical order. `awt` never edits `~/.claude/settings.json`, a project's settings or another drop-in. The owner's agents edit user settings routinely, and a merge there would be both a clobber risk and something an agent could undo.

**Generation:**

- `init --kind root` writes the drop-in;
- any `awt` run whose policy hash changed rewrites it (section 5.5), by temp file and `rename`;
- installing needs `sudo`, so `awt` never installs it.

**Doctor checks:**

- `fail` when the policy seals any class from `claude` and no Claude settings source that `doctor` can read carries every generated deny rule. Sources checked: the drop-in directory, `managed-settings.json`, and `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`. The `fix:` line prints the exact command: `sudo install -m 644 "$AWT_STORE/claude/50-awt-origin.json" "/Library/Application Support/ClaudeCode/managed-settings.d/"`.
- `warn` when the installed file differs from the generated one, for example after a policy change.

**Fallback:** an owner who will not use `sudo` can paste the same JSON into user settings by hand. `doctor` accepts that, but warns that agents can edit it.

The node template (`.claude/settings.json` written by `init`) is unchanged. It keeps detection only, and nothing in it is required (SPEC rule 7).

### 7.4 What cannot be made airtight

| Path around | Covered by | Gap |
|---|---|---|
| An arbitrary script that builds the path at run time (a `.py` file, `node -e` with string concatenation, `find / -name events.jsonl`) | Only the Claude Code **sandbox**, which merges permission `Read`/`Edit` deny rules into the OS sandbox for Bash and its children | Without the sandbox: open. awt does not turn the sandbox on (owner choice, section 14) |
| Recursive search over an ancestor (`rg secret ~/.local/share`) | Sandbox | Without the sandbox: open |
| A symlink made earlier, or by a non-Claude agent | Deny rules check the resolved target; the guard uses `realpath` | None for built-in tools. Bash through a symlink to an ancestor of `sealed/` plus a script: as above |
| A Claude model under **opencode** via Paseo | `AWT_MODEL` from the plugin, so every `awt` read filters. The plugin's `agent.permission.before` now **denies** a request from a Claude-family agent whose target (opencode `external_directory` `input.patterns`, Claude `filePath`) resolves into `sealed/` or is an edit of the policy file. The store is outside the agent's cwd, so opencode always asks for it, which makes this reliable. If opencode's config has path rules for `read`, the plugin adds a deny for `sealed/` to the agent's config at open (verify, G4) | Bash: opencode's own `bash` permission is not path-aware, so `cat` in a shell request is checked by the plugin only when the request carries the command (`detail.type: shell`). opencode 2.x requests carry no input |
| A Claude model under **pi** | `AWT_MODEL` from the plugin; `awt` reads filter | pi has no permission prompts and no hooks that `awt` installs. A direct `cat` of `sealed/` works. Option, not in this design: a pi extension that blocks tool calls naming `sealed/` |
| pi or opencode **without** the plugin | The `unknown` reader gets the strictest view | Direct file reads are open |
| `awt ui` | Section 9.3 | None for the full view: it needs a token |
| Paseo's MCP tools (`get_agent_activity` and others) that return another agent's timeline | Not `awt` data | Open: a Claude agent can read a deepseek agent's activity through Paseo |
| The provider's own stores (`~/.pi/agent/sessions`, opencode's `opencode.db`, `~/.claude/projects` when Claude Code ran a non-Claude model, `~/.paseo`) | Not `awt` data | Open. They hold the same text the store holds. Optional deny rules are listed in section 14 |

Same-uid file modes (600, 700) do not stop an agent: every agent runs as the owner. The modes stop other users and keep the data out of sync tools. The real walls are Claude Code's permission rules, the sandbox when it is on, and awt's filtering.

## 8. Writes

### 8.1 Placement

At `emit`, the row's class is `family(model, by)` (section 3) under the current policy.

| Writer | `model` | Class (default) | Lands in |
|---|---|---|---|
| Claude agent (Claude Code, or a Claude model under pi or opencode) | its model, or `unknown:unset` standalone | `claude` / `unknown` | tree log |
| Person (`--by person`) | `unknown:unset` | `person` | tree log |
| Non-Claude agent | its model (plugin `AWT_MODEL`) | `deepseek`, `openai`, ... | `sealed/<class>/nodes/<nid>/events.jsonl` |
| Agent with no model and no markers | `unknown:unset` | `unknown` | tree log (section 5.2) |
| Plugin writes for an agent (auto state, receipts, detected effects) | the agent's current model (`--model`, as now) | the agent's class | as for that agent |
| Claude Code hook (detected effect) | the payload's model, else the process model | usually `claude` | tree log |
| `ingest` | per row (section 6.4) | per row | `log/` or `sealed/<class>/log/` |

**Rule:** a row lands in the tree log, or in `log/`, exactly when its class is in the open set at write time. Otherwise it lands under `sealed/<class>/`.

### 8.2 Exceptions

- **Structural rows stay in the tree.** These are `node` rows (`kind`, `name`, `key`) and `status` rows. Without them, readers would disagree on what the tree is and whether a node is done. They keep their `model`, and reads still label them, but they are never sealed. This is a deliberate leak of existence and lifecycle (section 9.4).
- **Chains stay together.** Every step of an effect (`begun`, `sent`, `not-sent`, `unknown`, `dropped`) lands in the partition of its `planned` row, whoever writes the step. That is usually the same agent, or a person who sees everything. State derivation validates the transitions within one file, so a chain must not be split. A writer that cannot see an effect cannot address it, since the id is not found.
- **Captures.** A sealed-class `capture` writes its body to `sealed/<class>/nodes/<nid>/context/<YYYYMMDD>-<slug>.md`. The row's `path` is `context/<file>`, and readers resolve it against the row's partition. Dedupe by body hash checks only the files the writer may read. A Claude capture of a body that deepseek already captured makes a new file in the tree and says nothing.
- **`supersede`** moves the agent's own files under `docs/`, which are not `awt` data (section 10). The `doc` row is placed by the writer's class.

### 8.3 A non-Claude agent writing into a node that Claude agents use

The non-Claude rows go to that node's sealed partition. A Claude agent in the node sees the node without them:

- the current state is the newest **visible** state;
- a question answered only by deepseek still reads as open;
- a decision that deepseek superseded still reads as current;
- `BRIEF.md` (open view) shows none of it.

Full readers see the merged view (section 6.3). Two effects follow:

- **Double answers.** A Claude agent may answer a question that deepseek already answered. In a merged view the earliest answer by `ts` is the answer, and later ones show in `list questions --all` as `also answered`. They are not quarantined, because each file is valid on its own.
- **Duplicate plans.** `effect plan` checks keys only in the effects the writer can see. Two partitions can therefore each hold a plan with the same key. The **send** is still protected: the resend check reads all partitions (section 9.4).

### 8.4 A Claude-reader process never opens a sealed path

This is the invariant: no `awt` process whose reader may not read class `c` opens, stats or lists a path under `sealed/c/`, or a view database other than its own. The only exception is the resend check (section 9.4). It holds for:

- `emit`: a Claude reader writes only the tree;
- a chain step on a sealed effect, which the Claude reader cannot address;
- `BRIEF.md` regeneration, which uses the open view;
- every read.

Two consequences:

- `awt` keeps working under the Claude Code sandbox with the deny rules merged in.
- `ingest` started by a Claude reader (the `SessionEnd` hook, or `awt ingest` in Bash) is the one writer that must write sealed rows. Its attempt to write `sealed/` fails under a sandbox and is handled as an ordinary per-file error: the offsets are not saved, and a later run by the plugin daemon, cron or a person ingests the file. Without a sandbox it writes and **prints only open-view counts**: `ingested N rows from M claude files` counts the rows in the open set, and the error lines name only open-set files.

## 9. Reads

### 9.1 Every verb

Every read verb, and every write verb's read side, filters to the reader's view (section 6.3) and opens nothing outside it (section 8.4).

| Surface | Behaviour for a restricted reader |
|---|---|
| `resume`, `resume --json`, `resume --hook`, `--scope` | Brief from the merged visible rows. Every section's counts (inventory, quarantine, open questions, attention effects, Children, Task, Lineage) cover visible rows only |
| `BRIEF.md` | Always the open view (section 6.6) |
| `list <section>`, `--all`, `--json`, `list nodes`, `list tree` | Visible rows. `open_questions` and `attention_effects` count visible rows. `list context` adds sealed captures, by absolute path, only for readers allowed that class |
| `list --since --down --json` (plugin receipts) | Visible rows |
| `find TERM`, `--up`, `--down`, `--tree` | Event hits from visible rows. File hits are unchanged (section 10) |
| `find --sessions` | The reader's view database only |
| `find --like`, and the related lines of `decide` and `ask` | Candidates from visible rows only. The per-call in-memory FTS sees nothing else |
| `effect show ID`, `effect begin/mark ID`, `answer ID`, `decide --supersedes ID` | A hidden id behaves exactly like a missing id: exit 4, same text |
| `status done` | Section 9.4 |
| `doctor` | Counts (quarantine, `unknown:*` models, store size and files) cover visible files. Sealed and policy-mismatch checks run only for full readers. For anyone else, one line: `ok: sealed checks skipped (run doctor as a person)`. This line always prints for a restricted reader, so it does not depend on whether sealed data exists |
| `ingest` summaries | Open-view counts (section 8.4) |
| `ui` | Section 9.3 |
| `awt_resume` (plugin) | `awt resume` run with `AWT_MODEL=<agent's current model>`. A Claude agent gets the Claude view, deepseek the full view |
| Brief after compaction | Claude Code: the `SessionStart` hook runs `resume --hook`, and `CLAUDECODE` makes it a Claude reader. Paseo: the static block tells the agent to call `awt_resume` again, so it is filtered as above |
| Plugin static prompt block | Two fixed variants chosen in `agent.create.before` from the configured model's class. The open-view variant is unchanged ("`$AWT_DIR/BRIEF.md` or the `awt_resume` tool"). The variant for readers that may read sealed classes says "call the `awt_resume` tool for your brief (`$AWT_DIR/BRIEF.md` shows only the shared part)". Both are static, so both cache |
| `AGENTS.md` block | Gains one static sentence, the same in every node: "`BRIEF.md` is the shared view; `awt resume` shows everything your model may read." It is static, so it reveals nothing about a node |
| relay | Worker briefs are Claude views (section 4.3). A non-Claude worker command would get its own view through `AWT_MODEL` |
| Plugin receipts and `awt.resend` timeline items | UI-only (never sent to a provider). Read with the agent's `AWT_MODEL`, so a receipt matches what the agent can see |

### 9.2 Doctor and the store for a full reader

A full reader's `doctor` adds:

- the count per class of rows whose current class is sealed but which sit in open files (section 5.5);
- a `nid` used twice;
- a symlinked `sealed/`;
- the drop-in check (section 7.3);
- the policy check (section 5.4).

### 9.3 `awt ui`

- A restricted reader serves a snapshot of **its own** view database, which is the open view under the default. This is today's behaviour.
- A person serves a snapshot of `full.db`, and the existing guard plugin gains a token. `awt` makes 32 random bytes and prints the URL with `?_awt=<token>` to the person's terminal only. The guard requires the token, or the cookie it sets on the first request, for every request. A local agent cannot `curl` the full UI without the token, which only the person's terminal shows.
- Without a token the full UI answers 403. The open view needs no token, because anyone allowed the open view can read `store.db` anyway.

### 9.4 What a Claude reader can learn

**Decision:** `awt` output never reports, counts or hints at hidden records. There are no placeholders, no "N hidden" lines, and no counts that include hidden rows. A hidden id is indistinguishable from a missing one.

The following leaks are deliberate or unavoidable, and are listed so that the owner can judge them:

1. **Structure.** `node` and `status` rows are open. A Claude reader sees that a deepseek agent's node exists, its name and key, and whether it is active or done (section 8.2). The Children line shows `out.md` age and size from the file system.
2. **Raw links in mixed sessions.** Visible rows of a session that switched models keep their raw content verbatim (ADR 0003: `raw` is never altered). Claude `parentUuid` values that point at hidden messages, `src_ref` line numbers and `seq` gaps show that hidden rows exist and roughly how many. Content never shows. Hiding this would mean rewriting `raw`, which ADR 0003 forbids.
3. **Resend check (safety beats isolation).** Before a send, the detection check reads **every** partition of the node's ledger. This is the one exception to section 8.4, and it runs in the hook or plugin process, never in a read verb. If an identical send is already `sent` or `unknown` in a partition the caller cannot see, the hook answers `ask` with a reason that names nothing: `awt: an identical send is already recorded by another agent; a person must decide. fix: a person runs awt effect show in a full view`. Claude Code shows an `ask` to the person. The Paseo plugin shows `awt.resend` in the UI only. Without this, the same comment could be posted twice.
4. **`status done`.** The done gate must see every open question and effect. A restricted reader cannot read sealed rows, but `awt` may **stat** (never open) the existence of `sealed/*/nodes/<nid>` for the node and its descendants. If any exists, `status done` from a restricted reader is refused with `error: this node has records your model cannot see; fix: a person (or the Paseo archive) runs awt status done`. That leaks one bit: "some sealed data exists here". The plugin's archive path runs as `AWT_READER=full`, so it is unaffected.
5. **File-system metadata outside `sealed/`.** Offsets keys in `ingest/` name source files, and the file names in the providers' own directories are visible. Nothing in `ingest/` holds content (the spool moved to `sealed/_spool/`).

## 10. Not `awt` data

Files that agents write with their own tools are the agents' files, like the repository code that a deepseek agent commits and a Claude agent later reads. These include:

- the repository;
- `docs/`, `outbox/`, `misc/` and `scratch/` in a node;
- a subagent's `out.md`;
- effect body files.

`awt` cannot know their origin, does not move them and does not hide them. `find` and the listings show them as now.

**Possible later step:** for nodes whose `node` row was written with a sealed-class model, the plugin could set `AWT_DIR` for a non-Claude agent to a node whose working files live under `sealed/`. That would break the rule that the filesystem is the hierarchy (SPEC, Node tree), so it is not in this design. Owner question (section 14).

## 11. Migration: `migrate-origin`

`migrate-origin [--dry-run]` is a separate one-off script, like `migrate-wt` and `migrate-paseo`. It is not a verb. It is used once after the upgrade, and again after any tightening of the policy.

What it does:

1. **Run as a full reader.** It refuses without one, and refuses when `CLAUDECODE` is set.
2. **Lock.** It takes `flock` on `ingest/store.lock` and on each file as it rewrites it. It refuses (exit 1, `fix:`) while the Paseo daemon's spool or a log is being written, the same "run with the Paseo daemon stopped" rule that `migrate-paseo` has.
3. **Node logs.** For every node log in the tree (depth 8, 2,000 nodes), it takes the rows whose current class is sealed, excluding structural rows. It appends them to `sealed/<class>/nodes/<nid>/events.jsonl` (creating `.awt/nid` if needed), skipping rows already there (same bytes). It then rewrites the tree log without them: temp file, `fsync`, `rename`.
4. **Canonical files.** It does the same for every canonical file under `log/`. Rows go to `sealed/<class>/log/...` with `seq` unchanged.
5. **Paseo spool.** It moves `ingest/paseo.spool.jsonl` to `sealed/_spool/`.
6. **Derived state.** It deletes nothing else and rebuilds both views (`ingest --rebuild`). It regenerates every `BRIEF.md` and writes the drop-in.
7. **Report.** It writes `sealed/migration-report.md` with counts per class and node and every file rewritten. The report holds sealed facts, so it lives under `sealed/`.
8. **Exit codes.** It exits 1 if any row read was neither kept nor moved.

**Git history.** Rewriting a node log is the one place where `awt` removes rows from an append-only file. It is a person's explicit act, and the report says so. A tree that is a git repository keeps the old rows in its history: the report lists each such node and says that history still holds sealed rows. `awt` never rewrites git history.

**Before migration:** reads already filter by class (section 5.5), so no `awt` output shows hidden data. `cat` of the old files still does, and `doctor` warns until the script has run.

## 12. Interaction with the open PRs

The stack is #13 → #14 → #15 → #17/#18 → phase 5. This feature touches:

- `emit`, `load` and the tree walks;
- `ingest` and `build_store`;
- the hook entry point;
- the plugin's `awt()` runner, permission hook and prompt block.

Phase 5 is being changed right now (review fixes).

**Recommendation:** make this its own PR on top of phase 5, branch `feat/v2-origin-isolation`. Start the build only after the phase 5 review fixes are pushed, and rebase onto them, so that the two never edit `emit`, `load` or `build_store` at once. Keep one PR, with one commit per slice in this order:

1. classifier, policy and reader resolution (no behaviour change while nothing is sealed);
2. write placement, merged load and the read filters;
3. ingest placement and the two views;
4. Claude Code drop-in, guard and `doctor`;
5. plugin: per-agent `AWT_MODEL` env, the permission deny, the block variants and the TypeScript classifier;
6. `migrate-origin`.

Each slice is green on its own. `SPEC.md` changes go in the same commit as the behaviour (the SPEC delta is in section 15).

### Size

| Part | Lines (estimate) |
|---|---|
| `awt` (classifier, policy, reader, placement, merged load, filters, ingest placement, views, guard, drop-in, doctor, ui token) | 1,100–1,400 |
| `migrate-origin` | 300 |
| `relay` | 10 |
| Plugin (TypeScript) | 250–350 |
| Tests (unit, chaos, plugin) | 1,500–2,000 |
| `SPEC.md`, `docs/schema.md`, `tests/TEST-SPEC.md` | 200 |

That is about 3,500–4,000 lines in all: one builder for about 3–4 working sessions, then two reviews.

## 13. Test plan

Tests come first, as `AGENT-RULES.md` requires. The fixtures use the fictional `parsekit` project. Token-shaped strings are built at run time.

### Unit (`tests/test_origin.py`)

1. **Vectors.** Every vector in section 3.5, with each normalisation step tested on its own. The file is `tests/fixtures/model-families.json`, shared with the plugin.
2. **Policy:**
   - the default when the file is missing;
   - each validation failure gives the fail-closed view and a `doctor` fail;
   - `models` overrides, `provider_defaults` and `families` precedence;
   - the reserved names;
   - a policy holding a regex outside the shared subset is refused;
   - there is no `AWT_POLICY` variable (grep test).
3. **Reader matrix:** `CLAUDECODE` × `AWT_MODEL` (Claude, deepseek, `unknown:unset`, `pi:default`) × `AWT_READER=full` × TTY or not × `AWT_BY`. Expected per section 4.1. In particular:
   - `CLAUDECODE` with `AWT_MODEL=deepseek` gives `claude`;
   - `CLAUDECODE` with `AWT_READER=full` gives `claude`;
   - `--model gpt-5` on a read does not change the reader.
4. **Placement:**
   - every writer in the section 8.1 table;
   - structural rows stay in the tree;
   - effect chains follow their planned row;
   - sealed captures;
   - `.awt/nid` is created once with `O_EXCL`.
5. **Merged load:**
   - order by `ts`, then tree before sealed;
   - the latest state, task and ref across partitions;
   - an earliest-wins double answer;
   - a supersede across partitions;
   - quarantine counted per file.
6. **Filters:** each surface in the section 9.1 table, for a Claude reader and a full reader, on one fixture tree where deepseek wrote into a shared node:
   - nothing of deepseek's appears in output, `--json`, counts or exit codes (a hidden id gives exit 4 with byte-identical stderr to a missing id);
   - `BRIEF.md` is identical whoever wrote last.
7. **No-open invariant.** Run every verb as a Claude reader under `sys.addaudithook`, recording `open`, `os.listdir`, `os.scandir` and `os.stat` paths. Assert that none is under `sealed/`, except the stat in the `status done` gate and the resend check in `ingest --event`.
8. **Ingest:**
   - the mixed-session fixture (Claude → deepseek → Claude) splits into two files with dense global `seq`;
   - carry-forward and same-read look-ahead;
   - a rebuild re-places nothing;
   - the dedupe across both files;
   - the summary counts the open set only for a Claude reader;
   - a failed sealed write is a per-file error and the offset is not saved.
9. **Views:**
   - `store.db` holds no sealed row in any table, including `canonical`, `fts_text` and `usage`;
   - `full.db` holds all rows;
   - each view is byte-stable;
   - a changed policy hash rebuilds both;
   - with nothing sealed, `full.db` is not built.
10. **Policy change:**
    - loosening needs no move, and the drop-in and views follow;
    - tightening filters at once, `doctor` counts the rows in open files, and every `BRIEF.md` is regenerated.
11. **Guard (unit):** the path resolution cases: `~`, `$AWT_STORE`, globs, `cd x &&`, a relative path, a symlink, `realpath` of a not-yet-existing tail.
12. **`migrate-origin`:**
    - a dry run;
    - an idempotent rerun;
    - a crash between append and rename (both files are readable, and no row is lost or duplicated in any view);
    - the report location;
    - the git-history warning.
13. **`awt ui`:** the full view needs the token, and the open view does not.

### Chaos (`tests/chaos.py`, new section "origin")

The attacker is a Claude reader with `CLAUDECODE=1` that tries every path against a fixture store holding deepseek data. Each attempt is fed to the hook as a real payload and also run against `awt` directly. Every attempt must end **denied** (hook JSON) or **filtered** (no sealed byte in the output):

- Read, Grep and Glob with `path` or `pattern` into `sealed/`, and Read through a symlink;
- Edit and Write on the policy file and on a sealed log;
- `cat`, `head`, `sed -n`, `grep`, `rg`, `sqlite3` on `sealed/_views/full.db`, `cp`, `cp -r` of the store root, `tar`, `rsync`, `ln -s`, `find … -exec cat`, `python3 -c "open('…/sealed/…')"`, `cd ~/.local/share/awt-store && cat sealed/*/nodes/*/events.jsonl`, a heredoc python naming the path, `bash -c '…'`, and `$AWT_STORE/sealed` and `${HOME}` spellings;
- `unset CLAUDECODE; awt list`, `env -u CLAUDECODE awt resume`, `CLAUDECODE= awt find x`, `env -i awt list`;
- `AWT_READER=full awt list`, `AWT_MODEL=deepseek-chat awt resume` and a read verb given the global `--model gpt-5` (these run, but must be filtered);
- `awt effect show <hidden id>`, `awt answer <hidden q>` and `awt find --sessions <word only in deepseek text>`;
- `curl` against a running full `awt ui` without the token.

**Asserted known misses,** which pin the documented gaps so that a change is noticed:

- a Python script file that concatenates the path;
- `rg` over `~/.local/share` without the sandbox.

**Gated:** with Claude Code's sandbox on, the same script is denied by the OS (G3).

### Plugin (`paseo-plugin`, `npm test`)

- The TypeScript classifier passes `model-families.json`. It reads the table from a fake `awt help policy --json`.
- Agent-scoped calls carry `AWT_MODEL=<agent model>` in the child env, and system calls carry `AWT_READER=full` and no `AWT_MODEL`.
- `awt_resume` for a Claude agent and a deepseek agent on one node gives different briefs, and the Claude one contains nothing from deepseek.
- `agent.permission.before` **denies** a Claude-family agent's opencode `external_directory` request and its Claude `Read filePath` request into `sealed/`, and an edit of the policy file. It allows the same requests from a deepseek agent and leaves them alone. The node-dir allow rule is unchanged.
- The prompt block variant follows the configured model's class, and both variants are byte-stable.
- The auto state and detected effects of a deepseek agent land under `sealed/`.
- The spool lives at `sealed/_spool/`.
- A receipt for a Claude agent counts only visible rows.

### Gated live checks (record the results in `tests/TEST-SPEC.md`)

- **G1:** `CLAUDECODE` is present in Claude Code hook processes and Bash tool commands, standalone and under Paseo.
- **G2:** Paseo's Claude agents load `managed-settings.d/` deny rules and hooks.
- **G3:** with the sandbox on, `Read` deny rules on `sealed/` block a Python script in Bash, and the `SessionEnd` ingest still runs (hooks are not sandboxed).
- **G4:** opencode's permission config (does `read` take path patterns?), and whether opencode and pi run bash with a TTY on stdin (section 4.1 rule 5).

## 14. Owner decisions needed

1. **Unknown origin:** visible (the default, as the requirement reads) or sealed? This means `unknown:unset` written by an agent and an unresolved `pi:default` or `opencode:default`. Sealing it is safer. It would also hide every record that a standalone agent with no model writes.
2. **Install the drop-in:** a one-time `sudo install` into `/Library/Application Support/ClaudeCode/managed-settings.d/` (section 7.3). Without it, hard isolation for Claude Code rests on user settings that agents can edit, or on nothing.
3. **Claude Code sandbox:** turning it on is the only thing that stops an arbitrary script from reading `sealed/` (section 7.4). It changes how every Bash command runs.
4. **Provider stores:** should the drop-in also deny `Read` on the providers' own stores, which hold the same text? These are `~/.pi/agent/sessions/**`, opencode's `opencode.db`, and `~/.paseo/**`. And `~/.claude/projects/**`, which would also stop Claude reading its own past transcripts. Paseo's MCP activity tools are a similar leak that `awt` cannot close.
5. **The two deliberate one-bit leaks:** the resend `ask` and the `status done` refusal (section 9.4, items 3 and 4). The alternatives are sending twice, or allowing `done` over open work that is hidden.
6. **Structural rows open:** `node` and `status` (section 8.2).
7. **Agents' own files:** should non-Claude agent nodes get their working files (`out.md`, `scratch/`) under `sealed/`? Not in this design (section 10).

## 15. SPEC.md delta

This text is to be applied in the build, in the same commits as the behaviour. Section names refer to `SPEC.md` on `feat/v2-phase5`.

### 15.1 Rules: add after rule 8

> 9. A model may read only what the origin policy allows (see "Origin isolation"). The data hidden from a reader lives where that reader's host is denied, and every read filters by reader. When it is unclear who reads, show the least.

### 15.2 Layout created by `init`: add a line

> `.awt/nid`  node id (16 hex), `O_EXCL`, never rewritten; keys the node's sealed rows in the store

### 15.3 Events: Model tracking, append

> The row's **class** is `family(model, by)` (see Origin isolation). It decides where `emit` writes the row: the node's `.awt/events.jsonl` when the class is in the open set, else `$AWT_STORE/sealed/<class>/nodes/<nid>/events.jsonl`. `node` and `status` rows always go to the node's log. Effect steps go wherever their `planned` row is.

### 15.4 Reading, replace the first sentence

> One function `load()` is the only reader. It reads the node's log and, for each sealed class the reader may read, `sealed/<class>/nodes/<nid>/events.jsonl`, merges them by `ts` (ties: the node's log first, then class name, then file order), and drops every row whose current class the reader may not read. Within one file, **file order is canonical**; across files, merged order is.

The rest of the paragraph stays. Add:

> Quarantine counts are per file, and a reader sees only the counts of files it may read. A hidden id behaves exactly like a missing one.

### 15.5 Verbs

- `resume`: append "Filtered by reader (Origin isolation)."
- `list`: append "Only rows the reader may read; counts likewise."
- `find`: append "Event hits and `--like` candidates come only from rows the reader may read; `--sessions` searches the reader's view database."
- `status`: append "A reader that may not read every sealed class is refused `done` when any `sealed/*/nodes/<nid>` exists for the node or a descendant (stat only), with `fix:` naming a person."
- `ingest`: append "Summaries count only rows in the reader's view."

### 15.6 BRIEF.md, add a bullet

> - **Open view:** `BRIEF.md` is always the brief of the open view, the strictest view of the policy, whoever writes it. Readers allowed more use `resume` or `awt_resume`. When the policy's hash changes, the first `awt` run regenerates every `BRIEF.md` in the tree (walk limits as usual).

### 15.7 Effects, Detected effects: add a bullet

> - **Across partitions:** the resend check in `ingest --event` reads every partition of the node's ledger, the one place a restricted process reads sealed rows. A resend of a sealed effect asks with a reason that names nothing: `awt: an identical send is already recorded by another agent; a person must decide. fix: a person runs awt effect show in a full view`. The new detected rows are placed by their own class.

Change "This is labelling, not a permission system" to:

> This is labelling, not a permission system; the only thing `awt` ever denies is the origin guard (Origin isolation).

### 15.8 doctor, add

> `fail`: invalid origin policy; the policy seals a class from `claude` and no readable Claude settings source holds every generated deny rule (`fix:` prints the `sudo install` command for the drop-in). `warn`: the policy file is a symlink, not owned by the user, or writable by others; the installed drop-in differs from the generated one; (full reader only) rows of a sealed class in open files, with a count per class and the fix `migrate-origin`; a `nid` used twice; `sealed/` is a symlink or readable by others. A restricted reader gets `ok: sealed checks skipped (run doctor as a person)`, and its counts cover only the files it may read.

### 15.9 ingest

- **Store:** append "`sealed/` and everything under it are mode 700/600 even inside an existing store. The Paseo spool is `sealed/_spool/paseo.spool.jsonl`."
- **Output:** append:

  > Each canonical row also has `model`: the row's effective model (its own model, else the previous row's in that session, else the first model later in the same read, else empty, which is class `unknown`). `last_model` per file is kept in the offsets file. A row whose class is in the open set goes to `log/...`; otherwise to `sealed/<class>/log/...`, with the same file name. `seq` is dense and global across both. The duplicate check reads both. A failed write under `sealed/` is a per-file error like any other.

### 15.10 store.db

Replace the first line with:

> `$AWT_STORE/store.db` (mode 600) is the **open view**; `$AWT_STORE/sealed/_views/full.db` is the full view; a policy that gives some reader a view between the two adds `sealed/_views/<classes>.db`. Each is SQLite, derived only, built by the same code from the inputs and rows of its view, byte-stable on its own, with `schema_meta.policy_sha`; a different hash rebuilds it. `full.db` is not built while nothing is sealed. A reader opens only its own view.

Under **Inputs** add: "filtered per view by each row's current class".

### 15.11 Templates

- AGENTS.md block, after the brief sentence: "`BRIEF.md` is the shared view; `awt resume` shows everything your model may read."
- `.claude/settings.json` (the node template) is unchanged.

Add after it:

> ### Claude Code drop-in (`$AWT_STORE/claude/50-awt-origin.json`)
>
> Generated by `init --kind root` and whenever the policy hash changes; installed by a person into the managed-settings drop-in directory. It holds the deny rules and the two origin-guard hook entries:
>
> ```json
> {
>   "permissions": { "deny": [ "Read(//<STORE>/sealed/**)", "Edit(//<STORE>/sealed/**)", "Edit(//<STORE>/origin-policy.json)" ] },
>   "hooks": {
>     "PreToolUse": [
>       { "matcher": "Read|Edit|Write|MultiEdit|NotebookEdit|Grep|Glob|LS", "hooks": [ { "type": "command", "timeout": 10, "command": "b=$(cat); case \"$b\" in *sealed*|*origin-policy*) printf %s \"$b\" | <AWT> ingest --event --hook;; esac" } ] },
>       { "matcher": "Bash|mcp__.*", "hooks": [ { "type": "command", "timeout": 10, "command": "b=$(cat); case \"$b\" in *sealed*|*origin-policy*|*CLAUDECODE*) printf %s \"$b\" | <AWT> ingest --event --hook;; esac" } ] }
>     ]
>   }
> }
> ```
>
> `<STORE>` is the store's real path without its leading `/`; `<AWT>` is the absolute path of `awt`. A policy that lets `claude` read some sealed classes replaces the `sealed/**` pair with one `Read` and one `Edit` rule per denied class directory and per view database that is not Claude's.

### 15.12 Paseo plugin

- Configuration: add "Every `awt` call made for an agent runs with `AWT_MODEL` set to the agent's current model; the plugin's own calls (key lookup, archive) run with `AWT_READER=full` and without `AWT_MODEL`."
- `agent.create.before`: "two static variants of the block, by the class of the configured model (Origin isolation)."
- `agent.permission.before`: add a row:

  > Origin guard: a request from an agent whose model's class may not read a sealed class, with any target that resolves (`realpath`) into that class's directory or a view database not its own, or an edit of `origin-policy.json`, is answered **deny** with the origin-guard reason. This is the plugin's only deny.

- `awt_resume`: append "filtered by the calling agent's model."

### 15.13 relay

Append: "`relay` runs `awt resume --scope` with `AWT_MODEL` set to the unit's model."

### 15.14 New section "Origin isolation", after "store.db"

> ## Origin isolation
>
> Design and reasons: `docs/ORIGIN-ISOLATION.md`, `docs/adr/0009-claude-origin-isolation.md`.
>
> - **Class:** `family(model, by)`: `legacy` for empty or `unknown:legacy`; for other `unknown:*`, `person` when `by` is `person`, else `unknown`; then the policy's exact `models`; `<provider>:default` through `provider_defaults` (else `unknown`); then the normalised id (drop a trailing `[...]`, keep the text after the last `/`, drop `@...`, a trailing `:<digits>`, a leading `<word>:`, a leading region `us|eu|apac|ap|jp|au|ca|global|us-gov` `.`, a leading `anthropic.`) matched against the policy's `families` and then the shipped table (`claude`: `^claude(?:$|[-._:0-9])` or exactly `sonnet|opus|haiku|fable|opusplan`; then `openai`, `google`, `deepseek`, `meta`, `mistral`, `xai`, `qwen`, `moonshot`, `zhipu`, `amazon`, `cohere`); else `other`. The vectors in `tests/fixtures/model-families.json` are normative for awt and the plugin.
> - **Policy:** `$AWT_STORE/origin-policy.json` (optional, edited only by a person; no environment override): `version` 1, `readers` (reader family or `*` → list of classes or `*`), `provider_defaults`, `models`, `families`. Default: `claude` reads `claude`, `person`, `legacy`, `unknown`; every other family reads everything. A person reads everything. The **open set** is what every reader may read. Invalid policy: each agent reader reads only its own family, `person` and `legacy`; writes are placed by the default; `doctor` fails. `awt help policy [--json]` prints the default or effective policy.
> - **Reader:** `CLAUDECODE` set → `claude`; else a concrete `AWT_MODEL` → its family; else `AWT_MODEL` set → `unknown`; else `AWT_READER=full` → person; else stdin a TTY and `AWT_BY` unset or `person` → person; else `unknown`. `--model` and `--by` never change the reader. `unknown` reads the open set.
> - **Placement:** see Model tracking; captures of a sealed class go to `sealed/<class>/nodes/<nid>/context/`.
> - **Never open:** a process never opens, lists or stats a path under a sealed class it may not read, or a view database not its own, except the `status done` stat and the resend check.
> - **Origin guard:** `ingest --event --hook` denies a Claude Code tool call (file tools, Bash, MCP) that reaches into `sealed/` (paths resolved with `~`, `$HOME`, `$AWT_STORE`, `$XDG_DATA_HOME`, globs, `cd`, `realpath`; the store root itself with a recursive tool), that writes `origin-policy.json`, or that unsets or overrides `CLAUDECODE`, with `permissionDecision: deny` and a fixed reason. It runs only for a reader that may not read everything.
> - **Policy change:** nothing moves. Reads, view databases (`policy_sha`), `BRIEF.md` files and the drop-in follow the new policy. Rows of a newly hidden class already in open files stay until `migrate-origin` moves them; `doctor` counts them.
> - **`awt ui`:** serves the reader's own view; the full view needs the token printed on the person's terminal.
> - **Limits:** not covered are agents' own files, scripts that build paths at run time and recursive reads of an ancestor (only Claude Code's sandbox stops those), pi (no hooks), opencode shell requests without input, Paseo's activity tools, and the providers' own stores.

### 15.15 migrate-origin

Add a short section after `migrate-wt`, using the text of section 11 of this document.

### 15.16 Verbs count

Unchanged. `help policy` is help, not a verb, and `migrate-origin` is a separate script.

### 15.17 `docs/schema.md` (not SPEC, same commit)

- Schema version 7.
- A `class` column on `records`, `effects`, `sessions`, `turns`, `messages`, `tool_calls`, `permissions`, `usage`, `canonical` and `fts_ref`.
- `schema_meta.policy_sha`.
- One paragraph on views: which file, which rows. Avoid a name clash: `records.origin` (person, plugin or agent) and `effects.origin` (declared or detected) keep their meaning, which is why the new column is `class`.
