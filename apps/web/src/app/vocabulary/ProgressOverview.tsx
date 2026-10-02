'use client';

import { useMemo, useRef, useState } from 'react';
import { summarize, type Summary, type WordCards } from '../../../../remnote-plugin/src/stats';

// One indigo ramp, validated as ordinal (dataviz validate_palette.js); "not
// started" is neutral.
const STAGES = [
  { key: 'learned', label: 'learned', color: '#4338ca' },
  { key: 'learning', label: 'learning', color: '#818cf8' },
  { key: 'new', label: 'not started', color: '#e5e7eb' },
] as const;
const MAX_CHIPS = 16;

const dayLabel = (ms: number) => new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

function Trend({ trend }: { trend: Summary['trend'] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...trend.map((p) => p.learned));
  const x = (i: number) => (i / (trend.length - 1)) * 100;
  const y = (v: number) => 100 - (v / max) * 100;
  const line = trend.map((p, i) => `${x(i)},${y(p.learned)}`).join(' ');
  const point = hover === null ? null : trend[hover];

  const onMove = (e: React.PointerEvent) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const i = Math.round(((e.clientX - box.left) / box.width) * (trend.length - 1));
    setHover(Math.min(trend.length - 1, Math.max(0, i)));
  };

  return (
    <div className="mt-5">
      <div ref={ref} className="relative h-20 border-b border-gray-200 touch-none" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="block w-full h-full overflow-visible" aria-label={`Words learned over the last ${trend.length} days`}>
          <polygon points={`0,100 ${line} 100,100`} fill="#4f46e5" opacity={0.08} />
          <polyline points={line} fill="none" stroke="#4f46e5" strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {point && hover !== null && (
          <>
            <div className="absolute top-0 bottom-0 w-px bg-gray-400 pointer-events-none" style={{ left: `${x(hover)}%` }} />
            <div
              className="absolute w-2.5 h-2.5 -ml-[5px] -mt-[5px] rounded-full bg-indigo-600 ring-2 ring-white pointer-events-none"
              style={{ left: `${x(hover)}%`, top: `${y(point.learned)}%` }}
            />
            <div
              className="absolute -top-1 px-2 py-0.5 rounded-md bg-gray-900 text-white text-xs whitespace-nowrap pointer-events-none"
              style={{ left: `${x(hover)}%`, transform: hover > trend.length / 2 ? 'translate(calc(-100% - 8px), -100%)' : 'translate(8px, -100%)' }}
            >
              <strong>{point.learned}</strong> {hover === trend.length - 1 ? 'today' : dayLabel(point.day)}
            </div>
          </>
        )}
      </div>
      <div className="flex justify-between mt-1 text-[11px] text-gray-400">
        <span>{dayLabel(trend[0].day)}</span>
        <span>today</span>
      </div>
    </div>
  );
}

function Chips({ words, badge }: { words: { remId: string; root: string; lapses?: number }[]; badge?: boolean }) {
  const extra = words.length - MAX_CHIPS;
  return (
    <div className="flex flex-wrap gap-1.5">
      {words.slice(0, MAX_CHIPS).map((w) => (
        <span key={w.remId} className="inline-flex items-center gap-1.5 rounded-md bg-gray-100 px-2.5 py-1 text-sm text-gray-800">
          {w.root}
          {badge && w.lapses ? <span className="text-xs font-semibold text-amber-700">×{w.lapses}</span> : null}
        </span>
      ))}
      {extra > 0 && <span className="px-2.5 py-1 text-sm text-gray-400">+{extra}</span>}
    </div>
  );
}

/** Learned / learning / not started, the 90-day trend and the words worth
 *  attention, for whichever system schedules the reviews. */
export default function ProgressOverview({ words }: { words: WordCards[] }) {
  const [now] = useState(() => Date.now());
  const summary = useMemo(() => summarize(words, now), [words, now]);

  if (words.length === 0) {
    return <p className="text-sm text-gray-600">No words to learn yet. Words you save while watching or reading appear here.</p>;
  }

  return (
    <div>
      <div className="flex items-baseline gap-2.5">
        <span className="text-5xl font-bold tracking-tight tabular-nums text-gray-900">{summary.stages.learned}</span>
        <span className="text-gray-600">words learned</span>
        {summary.learnedLastWeek !== 0 && (
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
              summary.learnedLastWeek > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
            }`}
          >
            {summary.learnedLastWeek > 0 ? '+' : ''}
            {summary.learnedLastWeek} this week
          </span>
        )}
      </div>

      <Trend trend={summary.trend} />

      <div className="flex gap-0.5 h-2 mt-6 rounded overflow-hidden" role="img" aria-label={STAGES.map((s) => `${summary.stages[s.key]} ${s.label}`).join(', ')}>
        {STAGES.filter((s) => summary.stages[s.key] > 0).map((s) => (
          <div key={s.key} style={{ flexGrow: summary.stages[s.key], background: s.color, minWidth: 3 }} title={`${summary.stages[s.key]} ${s.label}`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-gray-600">
        {STAGES.map((s) => (
          <span
            key={s.key}
            className="inline-flex items-center gap-1.5"
            title={s.key === 'learned' ? 'Not due again for 3+ weeks, on every card of the word' : undefined}
          >
            <i className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
            <b className="font-semibold text-gray-900 tabular-nums">{summary.stages[s.key]}</b> {s.label}
          </span>
        ))}
      </div>

      {summary.newlyLearned.length > 0 && (
        <section className="mt-7">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2.5">New this week</h3>
          <Chips words={summary.newlyLearned} />
        </section>
      )}
      {summary.slipping.length > 0 && (
        <section className="mt-7">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2.5">Keeps slipping</h3>
          <Chips words={summary.slipping} badge />
        </section>
      )}
    </div>
  );
}
