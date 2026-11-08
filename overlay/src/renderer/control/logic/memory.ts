import type { FactView } from "../../../lib/protocol.generated.ts";

/** Everything memory holds about one subject's attribute: what's true now, and what it replaced. */
export interface FactGroup {
  key: string;
  subject: string;
  attribute: string;
  current: FactView[];
  /** Closed facts, newest first. Memory never overwrites, so these are the history. */
  past: FactView[];
  /** Two trusted sources disagree, so the partner will ask the player. */
  conflict: boolean;
}

const keyOf = (fact: FactView): string =>
  `${fact.subject.toLowerCase()}\u0000${fact.attribute.toLowerCase()}`;

/** Keeps the order facts arrived in, which is search rank or newest first. */
export function groupFacts(facts: readonly FactView[]): FactGroup[] {
  const groups = new Map<string, FactGroup>();
  for (const fact of facts) {
    const key = keyOf(fact);
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        subject: fact.subject,
        attribute: fact.attribute,
        current: [],
        past: [],
        conflict: false,
      };
      groups.set(key, group);
    }
    (fact.valid_to == null ? group.current : group.past).push(fact);
  }
  for (const group of groups.values()) {
    group.past.sort((a, b) => (b.valid_to ?? 0) - (a.valid_to ?? 0));
    group.conflict = group.current.length > 1;
  }
  return [...groups.values()];
}

/** "just now", "5 min ago", "3 h ago", or a date for anything older than a day. */
export function ago(unixSeconds: number, nowMs: number = Date.now()): string {
  const seconds = Math.max(0, nowMs / 1000 - unixSeconds);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return new Date(unixSeconds * 1000).toLocaleDateString();
}
