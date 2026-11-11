# awt

Keeps one awt node tree for everything you do in Paseo: a workspace node per Paseo workspace, a `main` task per workspace, an agent node per agent chat, and subagent nodes under their parents when Paseo reports the parent.

- Agents get `AWT_DIR` and `AWT_BY` in their environment, a short instruction block in their system prompt, and an `awt_resume` tool.
- When an agent finishes a turn without recording a handoff, it gets one follow-up asking for it, and no more until it has recorded state.
- Archiving an agent or workspace marks its node done (or paused when work is still open).
- The plugin approves only an agent's writes inside its own node dir, and never blocks an agent: if `awt` fails, the agent starts without it.

Settings come from the environment of the Paseo daemon: `AWT_BIN` (default `awt`), `AWT_ROOT` (default `~/.local/share/awt`), `AWT_TIMEOUT_MS` (default 5000).
