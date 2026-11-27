'use client';

import { useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { UserContext } from '@/context/UserContext';
import { LANGUAGES, LANGUAGE_LIST, type LanguageCode } from '@/lib/languages';
import { useCreateDemoAccount } from '@/app/hooks/useCreateDemoAccount';
import { useUpdateUserwords } from '@/app/hooks/useUpdateUserwords';
import { DEFAULT_PACE, PACES, ensureDailyWords, saveDailyPrefs } from '@/lib/dailyWords';
import { Thumbnail } from '../home/VideoCard';
import { formatDuration, percent, type HomeVideo } from '../home/homeApi';
import { ARROW, EntryNav, HaveAccount, Legal } from '../entry/EntryFrame';
import { SkyWall, pinToViewport } from '../entry/Sky';
import e from '../entry/entry.module.css';
import o from './onboarding.module.css';

type Level = 'A1' | 'A2' | 'B1' | 'B2';
type Step = 'language' | 'level' | 'topics' | 'pace' | 'done';

/** The starting levels: the sets in `languagelevels` (A1..B2 there), named
 *  for what the learner can do. The app starts being useful around A2, so
 *  the codes shown are one step up from the stored ones. */
export const START_LEVELS: { id: Level; label: string; words: number; can: string }[] = [
  { id: 'A1', label: 'A2', words: 650, can: 'I know the basics' },
  { id: 'A2', label: 'B1', words: 1300, can: 'I can handle simple everyday conversations' },
  { id: 'B1', label: 'B1+', words: 1950, can: 'I can follow clear speech on familiar topics' },
  { id: 'B2', label: 'B2', words: 4050, can: 'I can follow most native speakers' },
];

interface Preview {
  level: Level;
  words: number;
  topics: string[];
  videos: HomeVideo[];
  now: number;
  pace: Record<string, number>;
}

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const HIDDEN_TOPICS = new Set(['Other']);

export function previewQuery(language: string, level: Level, topics: string[]): string {
  const params = new URLSearchParams({ language, level });
  [...topics].sort().forEach((t) => params.append('topics', t));
  return `/api/onboarding/preview?${params}`;
}

/** "videos", "Cooking videos", "Cooking and Travel videos", "videos in your 3 topics" */
export function topicPhrase(topics: string[]): string {
  if (!topics.length) return 'videos';
  if (topics.length === 1) return `${topics[0]} videos`;
  if (topics.length === 2) return `${topics[0]} and ${topics[1]} videos`;
  return `videos in your ${topics.length} topics`;
}

const fmt = (n: number) => n.toLocaleString('en-US');

/** Where Split's panel sits; the language step's band glides into it. */
function panelRect() {
  const vw = document.documentElement.clientWidth;
  const left = vw / 2.08;
  return { left, top: 16, width: vw - left - 16, height: window.innerHeight - 32 };
}

const FLAGS: Partial<Record<LanguageCode, JSX.Element>> = {
  es: (<><rect width="30" height="20" fill="#C60B1E" /><rect y="5" width="30" height="10" fill="#FFC400" /></>),
  de: (<><rect width="30" height="20" fill="#FFCE00" /><rect width="30" height="13.3" fill="#DD0000" /><rect width="30" height="6.7" fill="#000" /></>),
  it: (<><rect width="30" height="20" fill="#CE2B37" /><rect width="20" height="20" fill="#fff" /><rect width="10" height="20" fill="#009246" /></>),
  fr: (<><rect width="30" height="20" fill="#EF4135" /><rect width="20" height="20" fill="#fff" /><rect width="10" height="20" fill="#0055A4" /></>),
};

const CHECK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
);

function PreviewCard({ video, showPercent }: { video: HomeVideo; showPercent: boolean }) {
  return (
    <article className={o.vid}>
      <div className={o.th}>
        <Thumbnail video={video} />
        {showPercent && <span className={o.badge}>{percent(video.understood)}</span>}
        {video.duration_s !== null && <span className={o.dur}>{formatDuration(video.duration_s)}</span>}
      </div>
      <h4>{video.title}</h4>
    </article>
  );
}

const LIVE_LANGUAGES: LanguageCode[] = ['es'];

interface OnboardingFlowProps {
  /** The language this flow sets up; in add mode, the one picked. */
  language?: LanguageCode;
  /** Adding a language to a signed-in account: no demo account, no sign-in
   *  link, and the languages the account already has are not offered. */
  adding?: { have: LanguageCode[]; start?: LanguageCode };
}

export default function OnboardingFlow({ language: fixed = 'es', adding }: OnboardingFlowProps) {
  const [picked, setPicked] = useState<LanguageCode | null>(
    adding?.start && LIVE_LANGUAGES.includes(adding.start) && !adding.have.includes(adding.start) ? adding.start : null,
  );
  const language = picked ?? fixed;
  const router = useRouter();
  const { user, initializeLanguage, setLanguage, fetchWithAuth } = useContext(UserContext);
  const { createDemoAccount } = useCreateDemoAccount();
  const { addWordsToUserwords } = useUpdateUserwords();

  const [step, setStep] = useState<Step>(picked ? 'level' : 'language');
  const [leaving, setLeaving] = useState(false);
  const [arrived, setArrived] = useState(picked !== null);
  const [level, setLevel] = useState<Level>('A1');
  const [hover, setHover] = useState<Level | null>(null);
  const [topics, setTopics] = useState<string[]>([]);
  const [pace, setPace] = useState<number>(DEFAULT_PACE);
  const [previews, setPreviews] = useState<Record<string, Preview>>({});
  const [error, setError] = useState('');
  const inflight = useRef(new Set<string>());

  const band = useRef<HTMLElement>(null);
  const bandWall = useRef<SVGSVGElement>(null);
  const panel = useRef<HTMLElement>(null);
  const panelWall = useRef<SVGSVGElement>(null);
  const split = step !== 'language';

  // Both skies are pinned to the viewport, so the band and the panel show
  // the same clouds in the same places.
  useLayoutEffect(() => {
    const pin = () => {
      pinToViewport(band.current, bandWall.current);
      pinToViewport(panel.current, panelWall.current);
    };
    pin();
    window.addEventListener('resize', pin);
    return () => window.removeEventListener('resize', pin);
  }, [split]);

  const load = useCallback(async (lv: Level, tp: string[]) => {
    const q = previewQuery(language, lv, tp);
    if (inflight.current.has(q)) return;
    inflight.current.add(q);
    try {
      const res = await fetch(`${API}${q}`);
      if (!res.ok) throw new Error(`preview ${res.status}`);
      const data = (await res.json()) as Preview;
      setPreviews((prev) => ({ ...prev, [q]: data }));
    } catch (err) {
      console.error('Onboarding preview failed:', err);
      inflight.current.delete(q); // try again next time it is asked for
    }
  }, [language]);

  // Every level at once, so hovering one shows its videos without a wait.
  // These effects fetch: their state is set when the answer arrives.
  useEffect(() => {
    if (step === 'level') START_LEVELS.forEach((l) => void load(l.id, []));
  }, [step, load]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (step === 'topics' || step === 'pace' || step === 'done') void load(level, topics);
  }, [step, level, topics, load]);

  const shownLevel: Level = step === 'level' ? (hover ?? level) : level;
  const shownTopics = step === 'level' ? [] : topics;
  const shown = previews[previewQuery(language, shownLevel, shownTopics)];
  const anyPreview = Object.values(previews)[0];
  const topicChoices = (anyPreview?.topics ?? []).filter((t) => !HIDDEN_TOPICS.has(t));
  const levelInfo = START_LEVELS.find((l) => l.id === shownLevel)!;

  /** The band fades its content, then glides into the panel's place over a
   *  sky that stays still; the level step then takes over in that spot. */
  const chooseLanguage = (code: LanguageCode) => {
    setPicked(code);
    const vw = document.documentElement.clientWidth;
    const b = band.current, w = bandWall.current;
    if (vw < 960 || !b || !w || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setStep('level');
      return;
    }
    setLeaving(true);
    window.setTimeout(() => {
      const B = b.getBoundingClientRect();
      const T = panelRect();
      Object.assign(b.style, { position: 'fixed', zIndex: '4', margin: '0', left: `${B.left}px`, top: `${B.top}px`, width: `${B.width}px`, height: `${B.height}px` });
      const ease = 'cubic-bezier(.5,0,.15,1)';
      const duration = 520;
      b.animate(
        [{ left: `${B.left}px`, top: `${B.top}px`, width: `${B.width}px`, height: `${B.height}px` },
         { left: `${T.left}px`, top: `${T.top}px`, width: `${T.width}px`, height: `${T.height}px` }],
        { duration, easing: ease, fill: 'forwards' });
      w.animate([{ left: `${-B.left}px`, top: `${-B.top}px` }, { left: `${-T.left}px`, top: `${-T.top}px` }],
        { duration, easing: ease, fill: 'forwards' });
      window.setTimeout(() => { setArrived(true); setStep('level'); }, duration + 20);
    }, 140);
  };

  const finish = async () => {
    setError('');
    setStep('done');
    try {
      // As before: a demo account per start, until the learner saves it.
      if (!adding && (!user || user.is_anonymous)) await createDemoAccount(level);
      await initializeLanguage(language, level);
      setLanguage(LANGUAGES[language]);
      await saveDailyPrefs(language, { pace, topics });
      try {
        await ensureDailyWords(language, fetchWithAuth, addWordsToUserwords);
      } catch (err) {
        // The next visit adds them; the account itself is ready.
        console.error('First daily words failed:', err);
      }
      router.push('/videos');
    } catch (err) {
      console.error('Setting up the account failed:', err);
      setError('Something went wrong setting up your account. Please try again.');
      setStep('pace');
    }
  };

  // ---------- language step: the sky band ----------
  if (!split) {
    const fade = leaving ? e.fadeOut : '';
    // Separate keys: React must not reuse the band, which the hand-over left
    // pinned in place with inline styles, as one of Split's columns.
    return (
      <div key="language" className={e.page}>
        <EntryNav right={adding ? <a href="/videos">Cancel</a> : <HaveAccount />} />
        <section className={`${e.band} ${e.bandTall}`} ref={band}>
          <SkyWall className={e.wall} wallRef={bandWall} />
          <h1 className={`${e.title} ${e.in} ${fade}`}>Which language are you learning?</h1>
        </section>
        <div className={`${e.edge} ${e.edgeTall} ${e.in3} ${fade}`}>
          <div className={e.langs}>
            {LANGUAGE_LIST.filter((lang) => !adding?.have.includes(lang.code)).map((lang) => {
              const live = LIVE_LANGUAGES.includes(lang.code);
              const flag = FLAGS[lang.code] && <svg className={e.flag} viewBox="0 0 30 20" aria-hidden="true">{FLAGS[lang.code]}</svg>;
              return live ? (
                <button key={lang.code} type="button" className={`${e.lang} ${e.live}`} onClick={() => chooseLanguage(lang.code)}>
                  {flag}
                  <span className={e.arrow}>{ARROW}</span>
                  <b>{lang.name}</b>
                  <span>30,000+ videos</span>
                </button>
              ) : (
                <div key={lang.code} className={e.lang} aria-disabled="true">
                  {flag}
                  <b>{lang.name}</b>
                  <span>Coming soon</span>
                </div>
              );
            })}
          </div>
        </div>
        <div className={fade}><Legal /></div>
      </div>
    );
  }

  // ---------- level, topics, pace: Split ----------
  const dots = (n: number) => (
    <div className={o.progress}>{[0, 1, 2, 3].map((i) => <i key={i} className={i === n ? o.on : ''} />)}</div>
  );
  const phrase = topicPhrase(topics);

  let left: JSX.Element;
  if (step === 'level') {
    left = (
      <>
        {dots(1)}
        <h1 className={o.h1}>How much {LANGUAGES[language].name} do you know?</h1>
        <div className={o.card} onMouseLeave={() => setHover(null)}>
          {START_LEVELS.map((l) => (
            <button key={l.id} type="button" className={`${o.row} ${level === l.id ? o.sel : ''}`}
              onMouseEnter={() => setHover(l.id)} onFocus={() => setHover(l.id)} onClick={() => setLevel(l.id)}>
              <span className={o.stack}>
                <span className={o.name}>{l.can}</span>
                <small>{l.label} · about {fmt(l.words)} words</small>
              </span>
              <span className={o.dot} />
            </button>
          ))}
        </div>
        <div className={o.next}>
          <p>Langfour will mark the <b>{fmt(START_LEVELS.find((l) => l.id === level)!.words)}</b> most common words as known to start with.</p>
          <button type="button" className={o.btn} onClick={() => setStep('topics')}>Continue</button>
        </div>
        <p className={o.after}><button type="button" className={o.textlink} onClick={() => { setLeaving(false); setArrived(false); setStep('language'); }}>Back</button></p>
      </>
    );
  } else if (step === 'topics') {
    left = (
      <>
        {dots(2)}
        <h1 className={o.h1}>What do you like to watch?</h1>
        <p className={o.lead}>Your first videos and daily words will lean towards these.</p>
        <div className={o.topics}>
          {topicChoices.map((t) => {
            const on = topics.includes(t);
            return (
              <button key={t} type="button" className={`${o.topic} ${on ? o.topicOn : ''}`} aria-pressed={on}
                onClick={() => setTopics((cur) => (on ? cur.filter((x) => x !== t) : [...cur, t]))}>
                {on && CHECK}{t}
              </button>
            );
          })}
        </div>
        <div className={o.next}>
          {topics.length ? (
            <>
              <p>{topics.length === 1 ? '1 topic' : `${topics.length} topics`} picked. You’ll still see everything else too.</p>
              <button type="button" className={o.btn} onClick={() => setStep('pace')}>Continue</button>
            </>
          ) : (
            <>
              <p className={o.hint}>Pick a few, or skip this.</p>
              <button type="button" className={o.textlink} onClick={() => setStep('pace')}>Skip</button>
            </>
          )}
        </div>
        <p className={o.after}><button type="button" className={o.textlink} onClick={() => setStep('level')}>Back</button></p>
      </>
    );
  } else if (step === 'pace') {
    left = (
      <>
        {dots(3)}
        <h1 className={o.h1}>How many new words a day?</h1>
        <p className={o.lead}>Each day Langfour adds them to your reviews, picked from the {phrase} you want to watch.</p>
        <div className={o.card}>
          {PACES.map((p) => (
            <button key={p} type="button" className={`${o.row} ${pace === p ? o.sel : ''}`} onClick={() => setPace(p)}>
              <span className={o.stack}>
                <span className={o.name}>{p} words a day</span>
                <small>
                  {shown ? <>In two weeks: <b>{fmt(shown.pace[String(p)] ?? 0)}</b> {phrase} at 90%+</> : <>&nbsp;</>}
                </small>
              </span>
              <span className={o.dot} />
            </button>
          ))}
        </div>
        {error && <p className={o.error} role="alert">{error}</p>}
        <div className={o.next}>
          <p className={o.hint}>You can change this any time.</p>
          <button type="button" className={o.btn} onClick={() => void finish()}>Start learning</button>
        </div>
        <p className={o.after}><button type="button" className={o.textlink} onClick={() => setStep('topics')}>Back</button></p>
      </>
    );
  } else {
    left = (
      <>
        <h1 className={o.h1}>Finding {LANGUAGES[language].name} videos for you</h1>
        <p className={o.lead}>
          Marking the {fmt(START_LEVELS.find((l) => l.id === level)!.words)} most common words as known, and adding your first {pace} words to your reviews.
        </p>
        <div className={o.loadBar}><i /></div>
      </>
    );
  }

  const tagText = step === 'level' || !topics.length ? 'Recommended at this level' : `${topics.length === 1 ? topics[0] : `${topics.length} topics`} at this level`;

  return (
    <div key="split" className={o.split}>
      <EntryNav right={adding ? <a href="/videos">Cancel</a> : <HaveAccount />} />
      <section className={o.left}>
        <div className={o.stage} key={step}>{left}</div>
      </section>
      <section className={o.panel} ref={panel}>
        <SkyWall className={o.wall} wallRef={panelWall} />
        <div className={`${o.pwin} ${arrived ? o.arrive : ''}`}>
          <div className={o.phead}>
            <h3>Videos</h3>
            <p className={o.label}><span className={o.tag}>{levelInfo.label}</span>{tagText}</p>
          </div>
          <div className={o.pgrid} key={`${shownLevel}|${shownTopics.join(',')}|${shown ? 1 : 0}`}>
            {shown
              ? shown.videos.map((v) => <PreviewCard key={v.id} video={v} showPercent />)
              : Array.from({ length: 12 }, (_, i) => (
                <article key={i} className={`${o.vid} ${o.skel}`}><div className={o.th} /><h4 /></article>
              ))}
          </div>
        </div>
      </section>
      <div className={o.legal}>
        <a href="https://www.langfour.com/privacy">Privacy</a>
        <a href="https://www.langfour.com/imprint">Imprint</a>
      </div>
    </div>
  );
}
