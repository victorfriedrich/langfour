'use client';

import { useMemo, useRef, useState } from 'react';
import { summarize, type Summary } from '../../../../remnote-plugin/src/stats';
import type { ProgressWord, SavedWord } from '../hooks/usePracticeProgress';

// The chart's indigo, a lighter step for "learning" and a neutral for "not
// started".
const STAGES = [
  { key: 'learned', label: 'learned', color: '#4f46e5' },
  { key: 'learning', label: 'learning', color: '#a5b4fc' },
  { key: 'new', label: 'not started', color: '#d1d5db' },
] as const;
const ROWS_SHOWN = 5;
// Ticks drawn per forgotten word; the count beside them says the rest.
const LAPSE_TICKS = 5;
const DAY_MS = 86_400_000;

const dayLabel = (ms: number) => new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

/** The smallest 1, 2 or 5 times a power of ten that is at least n. */
function niceCeil(n: number) {
  const power = 10 ** Math.floor(Math.log10(Math.max(1, n)));
  return [1, 2, 5, 10].map((m) => m * power).find((v) => v >= n) ?? 10 * power;
}

/** Each first of the month inside the trend, as its index. */
function monthStarts(trend: Summary['trend']) {
  return trend.flatMap((p, i) => (i > 0 && new Date(p.day).getDate() === 1 ? [i] : []));
}

function Trend({ trend }: { trend: Summary['trend'] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const max = niceCeil(Math.max(...trend.map((p) => p.learned)));
  const x = (i: number) => (i / (trend.length - 1)) * 100;
  const y = (v: number) => 100 - (v / max) * 100;
  const line = trend.map((p, i) => `${x(i)},${y(p.learned)}`).join(' ');
  const point = hover === null ? null : trend[hover];
  // Month labels too close to the ends would collide with the first day and "Today".
  const months = monthStarts(trend).filter((i) => x(i) > 10 && x(i) < 90);

  const onMove = (e: React.PointerEvent) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const i = Math.round(((e.clientX - box.left) / box.width) * (trend.length - 1));
    setHover(Math.min(trend.length - 1, Math.max(0, i)));
  };

  return (
    <div className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 text-xs tabular-nums text-gray-400">
      <div className="flex h-28 flex-col justify-between text-right leading-none">
        <span className="-mt-1">{max}</span>
        <span>{max / 2}</span>
        <span className="-mb-1">0</span>
      </div>
      <div ref={ref} className="relative h-28 border-b border-gray-200 touch-none" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        <div className="absolute inset-x-0 top-0 border-t border-dashed border-gray-200" />
        <div className="absolute inset-x-0 top-1/2 border-t border-dashed border-gray-200" />
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="relative block w-full h-full overflow-visible" aria-label={`Words learned over the last ${trend.length} days`}>
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
      <div className="relative col-start-2 mt-1.5 h-4">
        <span className="absolute left-0">{dayLabel(trend[0].day)}</span>
        {months.map((i) => (
          <span key={i} className="absolute -translate-x-1/2" style={{ left: `${x(i)}%` }}>
            {dayLabel(trend[i].day)}
          </span>
        ))}
        <span className="absolute right-0">Today</span>
      </div>
    </div>
  );
}

function startOfDay(ms: number) {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** The words saved on each of the last seven days, newest day first. */
function addedByDay(words: SavedWord[], now: number) {
  const today = startOfDay(now);
  // Day starts via the calendar, so a daylight-saving change doesn't shift them.
  const starts = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    return d.getTime();
  });
  const days = starts.map((start) => ({ start, words: [] as SavedWord[] }));
  for (const word of words) {
    if (word.addedAt > now) continue;
    days.find((d) => word.addedAt >= d.start)?.words.push(word);
  }
  for (const day of days) day.words.sort((a, b) => b.addedAt - a.addedAt);
  return days;
}

function addedDayLabel(start: number, i: number) {
  if (i === 0) return 'Today';
  if (i === 1) return 'Yesterday';
  return new Date(start).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });
}

/** One day's saved words on one line; a click shows them all. */
function DayRow({ label, words }: { label: string; words: SavedWord[] }) {
  const [open, setOpen] = useState(false);
  const text = words.map((w) => w.root).join(', ');
  return (
    <li className="grid grid-cols-[5.5rem_1.5rem_minmax(0,1fr)] items-baseline gap-3 py-2 text-sm">
      <span className="text-gray-900">{label}</span>
      <span className="tabular-nums text-gray-400">{words.length}</span>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`text-left text-gray-700 ${open ? '' : 'truncate'}`}
        title={open ? undefined : text}
      >
        {text}
      </button>
    </li>
  );
}

function relativeDay(ms: number, now: number) {
  const days = Math.round((startOfDay(now) - startOfDay(ms)) / DAY_MS);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return dayLabel(ms);
}

/** The words that would be learned but for a late review: most recently
 *  dropped first, each with its meaning and when it stopped counting. */
function Overdue({ overdue, words, now }: { overdue: Summary['overdue']; words: ProgressWord[]; now: number }) {
  const [all, setAll] = useState(false);
  const translations = useMemo(() => new Map(words.map((w) => [w.remId, w.translation])), [words]);
  if (overdue.length === 0) return null;
  const shown = all ? overdue : overdue.slice(0, ROWS_SHOWN);
  const thisWeek = overdue.filter((w) => w.since >= now - 7 * DAY_MS).length;

  return (
    <section className="mt-10">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-semibold text-gray-900">
          Overdue
          <span className="ml-2 font-normal tabular-nums text-gray-400">{overdue.length.toLocaleString()}</span>
        </h2>
        {thisWeek > 0 && <span className="text-sm tabular-nums text-gray-500">{thisWeek} this week</span>}
      </div>
      <p className="mt-1 text-sm text-gray-500">Learned, but reviewed too late to count. Review them to get them back.</p>
      <ul className="mt-2 divide-y divide-gray-100">
        {shown.map((w) => {
          const translation = translations.get(w.remId);
          return (
            <li key={w.remId} className="flex items-baseline gap-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">
                <span className="text-gray-900">{w.root}</span>
                {translation && <span className="ml-2 text-gray-500">{translation}</span>}
              </span>
              <span className="w-20 shrink-0 text-right tabular-nums text-gray-400" title="Stopped counting as learned">
                {relativeDay(w.since, now)}
              </span>
            </li>
          );
        })}
      </ul>
      {overdue.length > ROWS_SHOWN && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-1 py-1 text-sm text-gray-500 hover:text-gray-900">
          {all ? 'Show fewer' : `Show all ${overdue.length}`}
        </button>
      )}
    </section>
  );
}

/** The words forgotten in the last 30 days that aren't learned yet: most
 *  often forgotten first, each with its meaning and when it last slipped. */
function Forgotten({ slipping, words, now }: { slipping: Summary['slipping']; words: ProgressWord[]; now: number }) {
  const [all, setAll] = useState(false);
  const translations = useMemo(() => new Map(words.map((w) => [w.remId, w.translation])), [words]);
  if (slipping.length === 0) return null;
  const shown = all ? slipping : slipping.slice(0, ROWS_SHOWN);

  return (
    <section className="mt-10">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-semibold text-gray-900">
          Forgotten recently
          <span className="ml-2 font-normal tabular-nums text-gray-400">{slipping.length.toLocaleString()}</span>
        </h2>
        <span className="text-sm text-gray-500">last 30 days</span>
      </div>
      <ul className="mt-2 divide-y divide-gray-100">
        {shown.map((w) => {
          const translation = translations.get(w.remId);
          const times = `Forgotten ${w.lapses === 1 ? 'once' : `${w.lapses} times`}`;
          return (
            <li key={w.remId} className="flex items-baseline gap-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">
                <span className="text-gray-900">{w.root}</span>
                {translation && <span className="ml-2 text-gray-500">{translation}</span>}
              </span>
              <span className="flex shrink-0 items-center gap-2 self-center" title={times}>
                <span className="flex gap-0.5" aria-hidden>
                  {Array.from({ length: LAPSE_TICKS }, (_, i) => (
                    <i key={i} className={`block h-2.5 w-1 ${i < w.lapses ? 'bg-rose-400' : 'bg-gray-200'}`} />
                  ))}
                </span>
                <span className="w-6 tabular-nums text-gray-500">
                  <span className="sr-only">{times}</span>
                  <span aria-hidden>{w.lapses}×</span>
                </span>
              </span>
              <span className="w-20 shrink-0 text-right tabular-nums text-gray-400">{relativeDay(w.lastLapse, now)}</span>
            </li>
          );
        })}
      </ul>
      {slipping.length > ROWS_SHOWN && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-1 py-1 text-sm text-gray-500 hover:text-gray-900">
          {all ? 'Show fewer' : `Show all ${slipping.length}`}
        </button>
      )}
    </section>
  );
}

/** Learned / learning / not started, the 90-day trend, the words saved this
 *  week and the words overdue or forgotten recently, for whichever system schedules
 *  the reviews. */
export default function ProgressOverview({ words, saved }: { words: ProgressWord[]; saved: SavedWord[] }) {
  const [now] = useState(() => Date.now());
  const summary = useMemo(() => summarize(words, now), [words, now]);
  const added = useMemo(() => addedByDay(saved, now), [saved, now]);
  const addedThisWeek = added.reduce((n, d) => n + d.words.length, 0);

  if (words.length === 0) {
    return <p className="text-sm text-gray-600">No words to learn yet. Words you save while watching or reading appear here.</p>;
  }

  const change = summary.learnedLastWeek;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-semibold text-gray-900">
          Learned
          <span className="ml-2 font-normal tabular-nums text-gray-400">{summary.stages.learned.toLocaleString()}</span>
        </h2>
        {change !== 0 && (
          <span className="text-sm tabular-nums text-gray-500">
            {change > 0 ? '+' : '−'}
            {Math.abs(change)} this week
          </span>
        )}
      </div>

      <Trend trend={summary.trend} />

      <div className="flex gap-0.5 h-1.5 mt-6" role="img" aria-label={STAGES.map((s) => `${summary.stages[s.key]} ${s.label}`).join(', ')}>
        {STAGES.filter((s) => summary.stages[s.key] > 0).map((s) => (
          <div key={s.key} style={{ flexGrow: summary.stages[s.key], background: s.color, minWidth: 3 }} title={`${summary.stages[s.key]} ${s.label}`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2 text-sm text-gray-600">
        {STAGES.map((s) => (
          <span
            key={s.key}
            className="inline-flex items-center gap-1.5 tabular-nums"
            title={s.key === 'learned' ? 'Not due again for 3+ weeks, on every card of the word' : undefined}
          >
            {summary.stages[s.key].toLocaleString()} {s.label}
            <i className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: s.color }} />
          </span>
        ))}
      </div>

      <section className="mt-10">
        <h2 className="font-semibold text-gray-900">
          New this week
          <span className="ml-2 font-normal tabular-nums text-gray-400">{addedThisWeek.toLocaleString()}</span>
        </h2>
        {addedThisWeek === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No words saved in the last seven days.</p>
        ) : (
          <ul className="mt-2 divide-y divide-gray-100">
            {added.map(
              (day, i) => day.words.length > 0 && <DayRow key={day.start} label={addedDayLabel(day.start, i)} words={day.words} />,
            )}
          </ul>
        )}
      </section>

      <Overdue overdue={summary.overdue} words={words} now={now} />
      <Forgotten slipping={summary.slipping} words={words} now={now} />
    </div>
  );
}
