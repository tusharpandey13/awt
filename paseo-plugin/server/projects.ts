import { lstatSync, readFileSync } from "node:fs";

/** One row of Paseo's `projects/projects.json`, the fields awt uses. */
export interface ProjectRow {
  id: string;
  /** `customName ?? displayName`, or null when the row has neither. */
  name: string | null;
  rootPath: string | null;
  archived: boolean;
}

const MAX_BYTES = 4 << 20;
const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

/**
 * The projects in `file`, by id. Read-only and forgiving: a missing, oversized, symlinked or malformed file gives an empty map,
 * so an archive check never breaks a hook. The name is `customName ?? displayName`.
 */
export function readProjects(file: string): Map<string, ProjectRow> {
  const out = new Map<string, ProjectRow>();
  try {
    const st = lstatSync(file);
    if (!st.isFile() || st.size > MAX_BYTES) return out;
    const rows: unknown = JSON.parse(readFileSync(file, "utf8"));
    if (!Array.isArray(rows)) return out;
    for (const r of rows) {
      if (r === null || typeof r !== "object") continue;
      const o = r as Record<string, unknown>;
      const id = text(o.projectId);
      if (!id) continue;
      out.set(id, { id, name: text(o.customName) ?? text(o.displayName), rootPath: text(o.rootPath), archived: Boolean(o.archivedAt) });
    }
  } catch {
    /* no file, or not JSON: no archive information */
  }
  return out;
}
