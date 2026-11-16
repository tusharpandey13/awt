/** Added once to every new agent's system prompt. Static, so it caches. */
export const AWT_BLOCK = `[awt] Your task brief is $AWT_DIR/BRIEF.md (or the awt_resume tool). Record a choice with \`awt decide "..." --why "..."\` and a question for a person with \`awt ask "..."\`. Everything else is recorded for you. Never edit .awt/.`;

export const NUDGE =
  'Before you stop, record where things stand: awt state --now "where things stand" --next "the next concrete step". Then finish.';

export function withBlock(existing: string | undefined): string {
  if (existing?.includes(AWT_BLOCK)) return existing;
  return existing ? `${existing}\n\n${AWT_BLOCK}` : AWT_BLOCK;
}
