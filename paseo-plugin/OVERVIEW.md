# awt

Keeps one awt node tree for everything you do in Paseo: a workspace node per Paseo workspace, a `main` task per workspace, an agent node per agent chat, and subagent nodes under their parents when Paseo reports the parent.

- Agents get `AWT_DIR` and `AWT_BY` in their environment, a short instruction block in their system prompt, and an `awt_resume` tool.
- When an agent finishes a turn without recording a handoff, its last reply is kept as a state in scope `auto`. Nothing is sent to the chat. `AWT_NUDGE=1` sends one follow-up asking for a handoff instead.
- After every turn the chat gets one muted `awt-receipt` line showing what is stored in awt (decisions, notes, handoff, or nothing). A client renderer draws it; the model never sees it.
- The static prompt block points agents at `awt find --like` and tells them to call `awt_resume` again after compaction (Paseo has no session-hook field to do it natively).
- Archiving an agent or workspace marks its node done (or paused when work is still open).
- The plugin approves only an agent's writes inside its own node dir, and never blocks an agent: if `awt` fails, the agent starts without it.

Settings come from the environment of the Paseo daemon: `AWT_BIN` (default `awt`), `AWT_ROOT` (default `${XDG_DATA_HOME:-~/.local/share}/awt`), `AWT_TIMEOUT_MS` (default 5000), `AWT_AUTO_HANDOFF` (on; `0` stops keeping an agent's last reply as state in scope `auto` after a turn without a handoff), `AWT_NUDGE` (off; `1` sends a handoff follow-up prompt instead), `AWT_RECEIPT` (on; `0` off, `changes` only when something was stored), `AWT_RELATED` (forwarded to agents; related records after `decide` and `ask`).
