/** Added once to every new agent's system prompt. Static, so it caches. */
export const AWT_BLOCK = `[awt] Your work record is the awt node at $AWT_DIR. First call the awt_resume tool (or run \`awt resume\`); unless another agent started you, call it again after your context is compacted. Record with \`awt note|decide|ask|ref\`, and before you stop run \`awt state --now "..." --next "..."\`. Before a decision or question, \`awt find --like "topic"\` shows related records from every workspace; \`decide\` and \`ask\` list them too. Never edit .awt/. If another agent started you, skip the resume and write your result to $AWT_DIR/out.md.`;

export const NUDGE =
  'Before you stop, record where things stand: awt state --now "where things stand" --next "the next concrete step". Then finish.';

export function withBlock(existing: string | undefined): string {
  if (existing?.includes(AWT_BLOCK)) return existing;
  return existing ? `${existing}\n\n${AWT_BLOCK}` : AWT_BLOCK;
}
