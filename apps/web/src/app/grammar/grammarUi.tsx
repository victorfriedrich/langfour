import type { ConceptState } from '../hooks/useGrammar';

// The Practice page's indigo for rules in use, a lighter step for rules
// studied but not used yet, amber for rules due to be worked back in.
export const STATES: Record<ConceptState, { label: string; hint: string; color: string }> = {
  fresh: { label: 'in use', hint: 'You have used this rule correctly', color: '#4f46e5' },
  fading: { label: 'to refresh', hint: 'Due to come back in your next texts and chats', color: '#f59e0b' },
  studied: { label: 'studied', hint: 'In a chapter you started, not used correctly yet', color: '#c7d2fe' },
  'not yet': { label: 'not yet', hint: 'In a chapter you have not started', color: '#e5e7eb' },
};

export const LEGEND: ConceptState[] = ['fresh', 'fading', 'studied', 'not yet'];

export const LEVEL_NAMES: Record<string, string> = {
  a1: 'Beginner',
  a2: 'Elementary',
  b1: 'Intermediate',
  b2: 'Upper intermediate',
  c1: 'Advanced',
  c2: 'Proficient',
};

/** A chapter id without its language, for the URL: es.ser_estar_1 → ser_estar_1. */
export const chapterSlug = (id: string) => id.slice(id.indexOf('.') + 1);

/** One square per rule, in the chapter's order. */
export function ConceptStrip({ states, size = 'sm' }: { states: ConceptState[]; size?: 'sm' | 'md' }) {
  const box = size === 'md' ? 'h-2.5 w-2.5' : 'h-2 w-2';
  return (
    <span className="inline-flex flex-wrap gap-0.5" aria-hidden>
      {states.map((s, i) => (
        <i key={i} className={box} style={{ backgroundColor: STATES[s].color }} />
      ))}
    </span>
  );
}

/** The four states, each label followed by its square. */
export function Legend({ counts }: { counts?: Partial<Record<ConceptState, number>> }) {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-400">
      {LEGEND.map((s) => (
        <span key={s} className="inline-flex cursor-help items-center gap-1.5" title={STATES[s].hint}>
          {counts && <span className="tabular-nums text-gray-600">{(counts[s] ?? 0).toLocaleString()}</span>}
          {STATES[s].label}
          <i className="h-2 w-2" style={{ backgroundColor: STATES[s].color }} />
        </span>
      ))}
    </p>
  );
}

export function countStates(states: ConceptState[]) {
  const counts: Partial<Record<ConceptState, number>> = {};
  for (const s of states) counts[s] = (counts[s] ?? 0) + 1;
  return counts;
}
