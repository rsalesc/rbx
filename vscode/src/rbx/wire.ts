/**
 * Tolerant readers for values parsed out of rbx's YAML artifacts.
 *
 * The extension and the installed `rbx-cp` version drift independently, so
 * parsing must degrade rather than fail: unknown fields are ignored, and a
 * field of the wrong shape reads as absent instead of throwing. Nothing in this
 * file ever raises.
 */

export type Wire = unknown;

export function asRecord(value: Wire): Record<string, Wire> | undefined {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, Wire>;
}

export function asArray(value: Wire): Wire[] {
  return Array.isArray(value) ? value : [];
}

export function asString(value: Wire): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

export function asNumber(value: Wire): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function asBoolean(value: Wire): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

/**
 * Read a nested field by path, e.g. `field(root, 'metadata', 'copied_to', 'inputPath')`.
 *
 * rbx mixes conventions on the wire -- top-level skeleton keys are snake_case
 * (`group_entry`, `runs_dir`) while nested Pydantic models serialize camelCase
 * (`inputPath`, `configuredTime`) -- so keys are always spelled out literally
 * rather than derived.
 */
export function field(root: Wire, ...keys: string[]): Wire {
  let current: Wire = root;
  for (const key of keys) {
    const record = asRecord(current);
    if (record === undefined) {
      return undefined;
    }
    current = record[key];
  }
  return current;
}
