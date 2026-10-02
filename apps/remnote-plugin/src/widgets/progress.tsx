import { renderWidget, usePlugin, WidgetLocation } from '@remnote/plugin-sdk';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { startPairing, type Pairing } from '../api';
import { apiUrl, readToken, waitForApproval } from '../connection';
import { LANGUAGE_NAMES, STORAGE_LAST_SYNC } from '../constants';
import { summarize, type Stage, type Summary, type WordRef } from '../stats';
import { loadLinkedWords, syncNow, type LinkedWord, type SyncSummary } from '../sync';
import './progress.css';

const STAGE_NAMES: Record<Stage, string> = { learned: 'learned', learning: 'learning', new: 'not started' };
const BAR_ORDER: Stage[] = ['learned', 'learning', 'new'];
const MAX_CHIPS = 16;

const dayLabel = (ms: number) => new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

function Trend({ trend }: { trend: Summary['trend'] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...trend.map((p) => p.learned));
  const x = (i: number) => (i / (trend.length - 1)) * 100;
  const y = (v: number) => 100 - (v / max) * 100;
  const line = trend.map((p, i) => `${x(i)},${y(p.learned)}`).join(' ');

  const onMove = (e: React.PointerEvent) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const i = Math.round(((e.clientX - box.left) / box.width) * (trend.length - 1));
    setHover(Math.min(trend.length - 1, Math.max(0, i)));
  };
  const point = hover === null ? null : trend[hover];

  return (
    <div className="lf-trend">
      <div className="lf-trend-plot" ref={ref} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label={`Words learned over the last ${trend.length} days, now ${trend[trend.length - 1].learned}`}>
          <polygon className="lf-trend-area" points={`0,100 ${line} 100,100`} />
          <polyline className="lf-trend-line" points={line} vectorEffect="non-scaling-stroke" />
        </svg>
        {point && hover !== null && (
          <>
            <div className="lf-crosshair" style={{ left: `${x(hover)}%` }} />
            <div className="lf-dot" style={{ left: `${x(hover)}%`, top: `${y(point.learned)}%` }} />
            <div className={`lf-tip${hover > trend.length / 2 ? ' lf-tip-left' : ''}`} style={{ left: `${x(hover)}%` }}>
              <strong>{point.learned}</strong> {hover === trend.length - 1 ? 'today' : dayLabel(point.day)}
            </div>
          </>
        )}
      </div>
      <div className="lf-axis">
        <span>{dayLabel(trend[0].day)}</span>
        <span>today</span>
      </div>
    </div>
  );
}

function StageBar({ stages, total }: { stages: Summary['stages']; total: number }) {
  return (
    <div>
      <div className="lf-stagebar" role="img" aria-label={BAR_ORDER.map((s) => `${stages[s]} ${STAGE_NAMES[s]}`).join(', ')}>
        {BAR_ORDER.filter((s) => stages[s] > 0).map((s) => (
          <div key={s} className={`lf-seg lf-stage-${s}`} style={{ flexGrow: stages[s] }} title={`${stages[s]} of ${total} ${STAGE_NAMES[s]}`} />
        ))}
      </div>
      <div className="lf-legend">
        {BAR_ORDER.map((s) => (
          <span key={s}>
            <i className={`lf-swatch lf-stage-${s}`} />
            <b>{stages[s]}</b> {STAGE_NAMES[s]}
          </span>
        ))}
      </div>
    </div>
  );
}

function Chips({ words, badge }: { words: (WordRef & { lapses?: number })[]; badge?: boolean }) {
  const plugin = usePlugin();
  const open = async (remId: string) => {
    const rem = await plugin.rem.findOne(remId);
    if (rem) await plugin.window.openRem(rem);
  };
  const extra = words.length - MAX_CHIPS;
  return (
    <div className="lf-chips">
      {words.slice(0, MAX_CHIPS).map((w) => (
        <button key={w.remId} className="lf-chip" onClick={() => open(w.remId)}>
          {w.root}
          {badge && w.lapses ? <span className="lf-chip-badge">×{w.lapses}</span> : null}
        </button>
      ))}
      {extra > 0 && <span className="lf-chip lf-chip-more">+{extra}</span>}
    </div>
  );
}

function Connect({ onConnected, autoStart }: { onConnected: () => void; autoStart: boolean }) {
  const plugin = usePlugin();
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!pairing) return;
    let cancelled = false;
    waitForApproval(plugin, pairing, () => cancelled).then((approved) => {
      if (cancelled) return;
      if (approved) onConnected();
      else {
        setPairing(null);
        setError('The code expired. Start again.');
      }
    });
    return () => {
      cancelled = true;
    };
  }, [pairing, plugin, onConnected]);

  const start = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      setPairing(await startPairing(await apiUrl(plugin)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setStarting(false);
  }, [plugin]);

  useEffect(() => {
    if (autoStart) start();
  }, [autoStart, start]);

  const code = pairing?.user_code.replace('-', '') ?? '';

  return (
    <div className="lf-root lf-connect">
      <div className="lf-connect-card">
        <div className="lf-mark" aria-hidden>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1 1" />
            <path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1" />
          </svg>
        </div>
        <h1>Connect Langfour</h1>
        {pairing ? (
          <>
            <p>Approve this code in Langfour.</p>
            <div className="lf-code" aria-label={`Code ${pairing.user_code}`}>
              {[...code.slice(0, 4)].map((c, i) => <span key={i}>{c}</span>)}
              <span className="lf-code-gap" />
              {[...code.slice(4)].map((c, i) => <span key={i + 4}>{c}</span>)}
            </div>
            <a className="lf-button" href={pairing.verify_url} target="_blank" rel="noreferrer">
              Open Langfour
            </a>
            <span className="lf-waiting">
              <i className="lf-spinner" /> Waiting for approval
            </span>
            <button className="lf-link" onClick={() => setPairing(null)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <p>Words you save in Langfour become flashcards here, and your reviews show up as progress.</p>
            <button className="lf-button" onClick={start} disabled={starting}>
              {starting ? 'Connecting…' : 'Connect'}
            </button>
          </>
        )}
        {error && <p className="lf-error">{error}</p>}
      </div>
    </div>
  );
}

function Progress() {
  const plugin = usePlugin();
  const [words, setWords] = useState<LinkedWord[] | null>(null);
  const [lastSync, setLastSync] = useState<SyncSummary | undefined>();
  const [language, setLanguage] = useState<string | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [connectRequested, setConnectRequested] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    setConnected(!!(await readToken(plugin)));
    setWords(await loadLinkedWords(plugin));
    setLastSync(await plugin.storage.getSynced<SyncSummary>(STORAGE_LAST_SYNC));
  }, [plugin]);

  // Sync quietly and refresh, so the page is current without anyone asking.
  // Not connected, or another sync running: nothing to do, the page shows it.
  const sync = useCallback(async () => {
    setSyncing(true);
    await syncNow(plugin).catch(() => undefined);
    setSyncing(false);
    await load();
  }, [load, plugin]);

  // Show what RemNote has right away, then sync.
  useEffect(() => {
    load().then(sync);
  }, [load, sync]);

  // Opened by "Langfour: Connect": start pairing without a second click.
  useEffect(() => {
    plugin.widget
      .getWidgetContext<WidgetLocation.Pane>()
      .then((context) => setConnectRequested(!!context?.contextData?.connect))
      .catch(() => undefined);
  }, [plugin]);

  const languages = useMemo(() => [...new Set((words ?? []).map((w) => w.language))].sort(), [words]);
  const summary = useMemo(() => {
    if (!words) return null;
    const scoped = language ? words.filter((w) => w.language === language) : words;
    return summarize(scoped, Date.now());
  }, [words, language]);

  if (connected === false) return <Connect onConnected={sync} autoStart={connectRequested} />;

  if (!summary) return <div className="lf-root" />;

  if (words?.length === 0) {
    return (
      <div className="lf-root lf-connect">
        <div className="lf-connect-card">
          {syncing ? (
            <span className="lf-waiting">
              <i className="lf-spinner" /> Adding your Langfour words to RemNote
            </span>
          ) : lastSync?.error ? (
            <p className="lf-error">{lastSync.error}</p>
          ) : (
            <p>No words to learn yet. Words you save in Langfour appear here.</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="lf-root">
      <header className="lf-header">
        <h1>Langfour</h1>
        {languages.length > 1 && (
          <nav className="lf-tabs">
            {[null, ...languages].map((code) => (
              <button key={code ?? 'all'} className={language === code ? 'lf-tab lf-tab-on' : 'lf-tab'} onClick={() => setLanguage(code)}>
                {code ? LANGUAGE_NAMES[code] ?? code : 'All'}
              </button>
            ))}
          </nav>
        )}
      </header>
      {lastSync?.error && <p className="lf-error">Last sync failed: {lastSync.error}</p>}
      {lastSync?.warning && <p className="lf-error">{lastSync.warning}</p>}

      <div className="lf-hero">
        <span className="lf-hero-value">{summary.stages.learned}</span>
        <span className="lf-hero-label">
          words learned
          {summary.learnedLastWeek !== 0 && (
            <span className={summary.learnedLastWeek > 0 ? 'lf-delta' : 'lf-delta lf-delta-down'}>
              {summary.learnedLastWeek > 0 ? '+' : ''}
              {summary.learnedLastWeek} this week
            </span>
          )}
        </span>
      </div>

      <Trend trend={summary.trend} />
      <StageBar stages={summary.stages} total={summary.words} />

      {summary.newlyLearned.length > 0 && (
        <section>
          <h2>New this week</h2>
          <Chips words={summary.newlyLearned} />
        </section>
      )}

      {summary.slipping.length > 0 && (
        <section>
          <h2>Keeps slipping</h2>
          <Chips words={summary.slipping} badge />
        </section>
      )}

    </div>
  );
}

renderWidget(Progress);
