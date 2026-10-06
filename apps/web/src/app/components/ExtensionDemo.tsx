import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { BookCopy, Captions, Check, Highlighter, Languages, Layers, Maximize, Play, Plus, RotateCcw, Settings, Volume2 } from 'lucide-react';

/**
 * A hands-on imitation of the extension: hover (or tap) a highlighted word to
 * see its translation, then add it. Styled after the real popups in
 * apps/extension/src/translationPopup.css and reader.css so the demo matches
 * what people get after installing.
 */

type Word = { id: string; text: string; lemma?: string; translation: string };
type Segment = string | Word;

export type DemoMode = 'video' | 'reader';

const SUBTITLE: Segment[] = [
    'Nunca ',
    { id: 'pense', text: 'pensé', lemma: 'pensar', translation: 'I thought' },
    ' que ',
    { id: 'aprender', text: 'aprender', translation: 'to learn' },
    ' un ',
    { id: 'idioma', text: 'idioma', translation: 'language' },
    ' sería tan ',
    { id: 'divertido', text: 'divertido', translation: 'fun, enjoyable' },
    '.',
];

const ARTICLE: Segment[] = [
    'Madrid ',
    { id: 'despierta', text: 'despierta', lemma: 'despertar', translation: 'wakes up, rouses' },
    ' tarde, pero cuando lo hace, sus calles se ',
    { id: 'llenan', text: 'llenan', lemma: 'llenar', translation: 'fill up' },
    ' de vida. Los vecinos ',
    { id: 'charlan', text: 'charlan', lemma: 'charlar', translation: 'chat' },
    ' en las terrazas mientras el aroma del café recién hecho llega a cada ',
    { id: 'rincon', text: 'rincón', translation: 'corner' },
    ' del barrio.',
];

const ARTICLE_2: Segment[] = [
    'Al caer la noche, la ciudad cambia de ',
    { id: 'ritmo', text: 'ritmo', translation: 'rhythm, pace' },
    '. Los bares se ',
    { id: 'llenan2', text: 'llenan', lemma: 'llenar', translation: 'fill up' },
    ' de nuevo y las ',
    { id: 'conversaciones', text: 'conversaciones', lemma: 'conversación', translation: 'conversations' },
    ' se ',
    { id: 'alargan', text: 'alargan', lemma: 'alargar', translation: 'drag on, lengthen' },
    ' hasta la ',
    { id: 'madrugada', text: 'madrugada', translation: 'early morning hours' },
    ', como si nadie ',
    { id: 'quisiera', text: 'quisiera', lemma: 'querer', translation: 'wanted' },
    ' que el día terminara.',
];

const isWord = (s: Segment): s is Word => typeof s !== 'string';
const FIRST_WORD: Record<DemoMode, string> = {
    video: (SUBTITLE.find(isWord) as Word).id,
    reader: (ARTICLE.find(isWord) as Word).id,
};

const popupMotion = {
    initial: { opacity: 0, y: 6, scale: 0.96 },
    animate: { opacity: 1, y: 0, scale: 1 },
    exit: { opacity: 0, y: 4, scale: 0.98 },
    transition: { duration: 0.16, ease: [0.2, 0.8, 0.2, 1] },
};

function InteractiveText({
    segments,
    mode,
    added,
    open,
    hinted,
    onOpen,
    onClose,
    onAdd,
}: {
    segments: Segment[];
    mode: DemoMode;
    added: Set<string>;
    open: string | null;
    hinted: string | null;
    onOpen: (id: string) => void;
    onClose: () => void;
    onAdd: (id: string) => void;
}) {
    return (
        <>
            {segments.map((seg, i) => {
                if (!isWord(seg)) return <span key={i}>{seg}</span>;
                const isAdded = added.has(seg.id);
                const isOpen = open === seg.id;
                const wordClass =
                    mode === 'video'
                        ? isAdded
                            ? 'text-white'
                            : 'text-[#ffb732] hover:text-[#ffc95e]'
                        : isAdded
                          ? ''
                          : 'bg-[#ffecb3]/30 border-b border-dashed border-[#d9a760] px-px hover:bg-[#ffecb3]/50 hover:text-[#8B4513]';
                return (
                    <span
                        key={seg.id}
                        className="relative inline-block"
                        onMouseEnter={() => onOpen(seg.id)}
                        onMouseLeave={onClose}
                    >
                        {hinted === seg.id && (
                            <motion.span
                                aria-hidden
                                className={`pointer-events-none absolute -inset-x-1.5 -inset-y-0.5 rounded-md ${
                                    mode === 'video' ? 'ring-2 ring-[#ffb732]/70' : 'ring-2 ring-[#d9a760]/70'
                                }`}
                                initial={{ opacity: 0 }}
                                animate={{ opacity: [0, 1, 0], scale: [0.96, 1.04, 1.08] }}
                                transition={{ duration: 1.8, repeat: Infinity, ease: 'easeOut' }}
                            />
                        )}
                        <button
                            type="button"
                            data-word={seg.id}
                            aria-expanded={isOpen}
                            onClick={(e) => {
                                // Always open: on touch screens the tap also fires mouseenter,
                                // so toggling here would close it again. Tapping outside closes.
                                e.stopPropagation();
                                onOpen(seg.id);
                            }}
                            className={`cursor-pointer rounded-sm transition-colors duration-300 ${wordClass}`}
                        >
                            {seg.text}
                        </button>
                        <AnimatePresence>
                            {isOpen && (
                                <span
                                    className={`absolute left-1/2 z-20 -translate-x-1/2 ${
                                        mode === 'video' ? 'bottom-full pb-2.5' : 'top-full pt-2'
                                    }`}
                                >
                                    <motion.span
                                        {...popupMotion}
                                        {...(mode === 'reader' && { initial: { opacity: 0, y: -6, scale: 0.96 } })}
                                        onClick={(e) => e.stopPropagation()}
                                        className={`block ${mode === 'video' ? 'origin-bottom' : 'origin-top'}`}
                                    >
                                        {mode === 'video' ? (
                                            <VideoPopup word={seg} added={isAdded} onAdd={() => onAdd(seg.id)} />
                                        ) : (
                                            <ReaderPopup word={seg} added={isAdded} onAdd={() => onAdd(seg.id)} />
                                        )}
                                    </motion.span>
                                </span>
                            )}
                        </AnimatePresence>
                    </span>
                );
            })}
        </>
    );
}

function VideoPopup({ word, added, onAdd }: { word: Word; added: boolean; onAdd: () => void }) {
    return (
        <span className="block w-max min-w-[168px] rounded-xl border border-white/10 bg-[rgba(35,35,38,0.95)] p-3 text-left shadow-[0_12px_32px_-8px_rgba(0,0,0,0.6)] backdrop-blur">
            <span className="block text-[11px] font-normal tracking-wide text-white/50">
                {word.lemma ? `${word.text} · ${word.lemma}` : word.text}
            </span>
            <span className="mt-1 flex items-center justify-between gap-4">
                <span className="text-[15px] font-semibold text-white">{word.translation}</span>
                <button
                    type="button"
                    data-add={word.id}
                    onClick={onAdd}
                    disabled={added}
                    aria-label={added ? 'Added to flashcards' : 'Add to flashcards'}
                    className={`grid h-6 w-6 place-items-center rounded-md border transition-colors ${
                        added
                            ? 'border-emerald-400/40 bg-emerald-400/15 text-emerald-300'
                            : 'border-white/25 text-white hover:bg-white/15'
                    }`}
                >
                    <AnimatePresence mode="wait" initial={false}>
                        <motion.span
                            key={added ? 'check' : 'plus'}
                            initial={{ scale: 0.4, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.4, opacity: 0 }}
                            transition={{ duration: 0.15 }}
                        >
                            {added ? <Check size={13} strokeWidth={3} /> : <Plus size={13} strokeWidth={2.5} />}
                        </motion.span>
                    </AnimatePresence>
                </button>
            </span>
        </span>
    );
}

function ReaderPopup({ word, added, onAdd }: { word: Word; added: boolean; onAdd: () => void }) {
    const [main, ...rest] = word.translation.split(',').map((t) => t.trim());
    return (
        <span className="block w-max min-w-[220px] overflow-hidden rounded-md border border-black/[0.08] bg-white text-left font-serif shadow-[0_4px_15px_rgba(0,0,0,0.15)]">
            <span className="block border-b border-[#e2d1c3] bg-[#f8f5f0] px-4 py-3 text-[17px] font-bold text-[#5d2e0d]">
                {word.text}
                {word.lemma && ` (${word.lemma})`}
            </span>
            <span className="block px-4 py-3 text-[15px] leading-snug">
                <span className="block text-[#333]">{main}</span>
                {rest.map((t) => (
                    <span key={t} className="mt-1.5 block border-t border-[#f0e9e0] pt-1.5 italic text-[#666]">
                        {t}
                    </span>
                ))}
            </span>
            <button
                type="button"
                data-add={word.id}
                onClick={onAdd}
                disabled={added}
                className={`block w-full px-4 py-3 text-sm text-white transition-colors ${
                    added ? 'bg-[#9a764e]' : 'bg-[#8B4513] hover:bg-[#7a3c10]'
                }`}
            >
                {added ? 'Added to Flashcards ✓' : 'Add to Flashcards'}
            </button>
        </span>
    );
}

function AddedCounter({ count, tone }: { count: number; tone: 'dark' | 'light' }) {
    return (
        <AnimatePresence>
            {count > 0 && (
                <motion.div
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    className={`absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                        tone === 'dark'
                            ? 'bg-white/10 text-white ring-1 ring-white/15 backdrop-blur-md'
                            : 'bg-white/80 text-[#5d2e0d] ring-1 ring-[#e2d1c3] backdrop-blur'
                    }`}
                >
                    <Layers size={13} />
                    <span className="relative inline-flex h-4 w-2.5 justify-center overflow-hidden tabular-nums">
                        <AnimatePresence initial={false}>
                            <motion.span
                                key={count}
                                initial={{ y: 12 }}
                                animate={{ y: 0 }}
                                exit={{ y: -12 }}
                                transition={{ duration: 0.2 }}
                                className="absolute"
                            >
                                {count}
                            </motion.span>
                        </AnimatePresence>
                    </span>
                    in flashcards
                </motion.div>
            )}
        </AnimatePresence>
    );
}

function VideoStage(props: StageProps) {
    const reduce = useReducedMotion();
    const drift = (x: number[], y: number[], duration: number) =>
        reduce ? {} : { animate: { x, y }, transition: { duration, repeat: Infinity, repeatType: 'mirror' as const, ease: 'easeInOut' } };

    return (
        <div className="relative h-full w-full overflow-clip bg-[#0b0d14]" onClick={props.onClose}>
            {/* An abstract "scene" in place of real footage. */}
            <motion.div
                className="absolute -left-[10%] top-[5%] h-[70%] w-[55%] rounded-full bg-indigo-500/45 blur-[70px]"
                {...drift([0, 40], [0, 20], 9)}
            />
            <motion.div
                className="absolute right-[-5%] top-[-10%] h-[60%] w-[45%] rounded-full bg-amber-400/25 blur-[80px]"
                {...drift([0, -30], [0, 30], 11)}
            />
            <motion.div
                className="absolute bottom-[-20%] left-[35%] h-[55%] w-[40%] rounded-full bg-rose-500/25 blur-[80px]"
                {...drift([0, 30], [0, -20], 13)}
            />
            <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,rgba(0,0,0,0.55))]" />

            <AddedCounter count={props.added.size} tone="dark" />

            <div className="absolute inset-x-0 bottom-[22%] z-10 flex justify-center px-6">
                <p className="max-w-[90%] rounded-md bg-black/70 px-3 py-1.5 text-center text-[15px] leading-relaxed text-white md:text-lg">
                    <InteractiveText segments={SUBTITLE} mode="video" {...props} />
                </p>
            </div>

            <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent px-4 pb-3 pt-10">
                <div className="h-[3px] w-full overflow-hidden rounded-full bg-white/20">
                    <motion.div
                        className="h-full rounded-full bg-white/85"
                        initial={{ width: '18%' }}
                        animate={reduce ? undefined : { width: ['18%', '64%'] }}
                        transition={{ duration: 40, ease: 'linear', repeat: Infinity }}
                    />
                </div>
                <div className="mt-2.5 flex items-center justify-between text-white/80">
                    <div className="flex items-center gap-4">
                        <Play size={15} fill="currentColor" />
                        <Volume2 size={16} />
                        <span className="text-[11px] tabular-nums text-white/60">2:14 / 11:42</span>
                    </div>
                    <div className="flex items-center gap-4">
                        <Captions size={16} className="text-white" />
                        <Settings size={15} />
                        <Maximize size={15} />
                    </div>
                </div>
            </div>
        </div>
    );
}

function ReaderStage(props: StageProps) {
    const tools = [Languages, Highlighter, BookCopy, Settings];
    return (
        <div className="relative flex h-full w-full overflow-clip bg-[#f8f5f0]" onClick={props.onClose}>
            <div aria-hidden className="absolute inset-x-0 top-0 z-10 h-[3px] w-[28%] bg-[#8B4513]" />
            <div
                aria-hidden
                className="z-[5] flex w-11 shrink-0 flex-col items-center gap-5 border-r border-[#e2d1c3] bg-white pt-5 text-[#8B4513] shadow-[1px_0_5px_rgba(0,0,0,0.05)] md:w-[60px] md:pt-6"
            >
                {tools.map((Icon, i) => (
                    <Icon key={i} size={18} />
                ))}
            </div>
            <div className="relative flex-1 overflow-clip">
                <AddedCounter count={props.added.size} tone="light" />
                <article className="mx-auto h-full max-w-[32rem] bg-white px-6 pt-8 shadow-[0_2px_10px_rgba(0,0,0,0.08)] md:px-10 md:pt-10">
                    <h3 className="font-[Baskerville,Georgia,serif] text-xl font-bold leading-tight text-[#1a1a1a] md:text-[28px]">
                        La ciudad que nunca duerme
                    </h3>
                    <p className="mt-4 text-justify font-serif text-[14px] leading-[1.7] text-[#333] first-letter:float-left first-letter:pr-1 first-letter:pt-1 first-letter:text-[3.2em] first-letter:leading-[0.7] md:text-base">
                        <InteractiveText segments={ARTICLE} mode="reader" {...props} />
                    </p>
                    <p className="mt-4 text-justify font-serif text-[14px] leading-[1.7] text-[#333] md:text-base">
                        <InteractiveText segments={ARTICLE_2} mode="reader" {...props} />
                    </p>
                </article>
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-[#f8f5f0] to-transparent" />
            </div>
        </div>
    );
}

type StageProps = {
    added: Set<string>;
    open: string | null;
    hinted: string | null;
    onOpen: (id: string) => void;
    onClose: () => void;
    onAdd: (id: string) => void;
};

const SEGMENTS: Record<DemoMode, Segment[]> = { video: SUBTITLE, reader: ARTICLE };

// Scales every autoplay delay and cursor move; lower is faster.
const AUTOPLAY_PACE = 0.85;
// Idle time after the visitor's last interaction before the autoplay resumes.
const RESUME_AFTER_MS = 10_000;

type CursorState = { x: number; y: number; pressed: boolean; visible: boolean };

function FakeCursor({ cursor }: { cursor: CursorState }) {
    const move = { duration: 0.9 * AUTOPLAY_PACE, ease: [0.4, 0, 0.2, 1] as const };
    return (
        <AnimatePresence>
            {cursor.visible && (
                <motion.div
                    aria-hidden
                    className="pointer-events-none absolute left-0 top-0 z-30 drop-shadow-[0_2px_3px_rgba(0,0,0,0.35)]"
                    initial={{ opacity: 0, x: cursor.x, y: cursor.y }}
                    animate={{ opacity: 1, x: cursor.x, y: cursor.y, scale: cursor.pressed ? 0.82 : 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ x: move, y: move, scale: { duration: 0.12 }, opacity: { duration: 0.3 } }}
                >
                    <svg width="20" height="22" viewBox="0 0 20 22">
                        <path d="M2 1.5 L2 18 L6.4 13.9 L9.3 20.4 L12.3 19 L9.5 12.7 L15.6 12.7 Z" fill="#111" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" />
                    </svg>
                </motion.div>
            )}
        </AnimatePresence>
    );
}

/**
 * Plays the demo by itself while it is on screen: a cursor hovers a word,
 * adds it, moves on. The first real pointer movement, tap or focus inside the
 * demo hands control to the visitor; it resumes after 10 seconds without
 * interaction. Skipped for reduced motion.
 */
function useAutoplay({
    mode,
    enabled,
    stageRef,
    setOpenWord,
    setAdded,
}: {
    mode: DemoMode;
    enabled: boolean;
    stageRef: React.RefObject<HTMLDivElement | null>;
    setOpenWord: (w: { mode: DemoMode; id: string } | null) => void;
    setAdded: (fn: (prev: Set<string>) => Set<string>) => void;
}) {
    const [cursor, setCursor] = useState<CursorState>({ x: 0, y: 0, pressed: false, visible: false });

    useEffect(() => {
        const stage = stageRef.current;
        if (!enabled || !stage) return;

        let cancelled = false;
        let visible = false;
        const observer = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting), { threshold: 0.6 });
        observer.observe(stage);

        const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms * AUTOPLAY_PACE));
        const waitUntilVisible = async () => {
            while (!visible && !cancelled) await sleep(300);
        };
        // Point just inside the target, where a real cursor would rest on it.
        const pointAt = (selector: string) => {
            const target = stage.querySelector(selector);
            if (!target) return null;
            const t = target.getBoundingClientRect();
            const s = stage.getBoundingClientRect();
            return { x: t.left - s.left + t.width * 0.55, y: t.top - s.top + t.height * 0.55 };
        };
        const moveTo = (p: { x: number; y: number } | null) => p && setCursor((c) => ({ ...c, ...p }));

        const words = SEGMENTS[mode].filter(isWord).slice(0, 3);

        (async () => {
            await waitUntilVisible();
            await sleep(700);
            const rect = stage.getBoundingClientRect();
            setCursor({ x: rect.width * 0.82, y: rect.height * 0.86, pressed: false, visible: true });
            await sleep(500);

            while (!cancelled) {
                for (const word of words) {
                    await waitUntilVisible();
                    if (cancelled) return;
                    moveTo(pointAt(`[data-word="${word.id}"]`));
                    await sleep(1100);
                    if (cancelled) return;
                    setOpenWord({ mode, id: word.id });
                    await sleep(1000);
                    if (cancelled) return;
                    moveTo(pointAt(`[data-add="${word.id}"]`));
                    await sleep(950);
                    if (cancelled) return;
                    setCursor((c) => ({ ...c, pressed: true }));
                    await sleep(140);
                    setCursor((c) => ({ ...c, pressed: false }));
                    setAdded((prev) => new Set(prev).add(word.id));
                    await sleep(1300);
                    if (cancelled) return;
                    setOpenWord(null);
                    await sleep(600);
                }
                await sleep(1800);
                if (cancelled) return;
                setAdded(() => new Set());
                await sleep(800);
            }
        })();

        return () => {
            cancelled = true;
            observer.disconnect();
            setCursor((c) => ({ ...c, visible: false, pressed: false }));
        };
    }, [enabled, mode, stageRef, setOpenWord, setAdded]);

    return cursor;
}

export default function ExtensionDemo({ mode }: { mode: DemoMode }) {
    const [added, setAdded] = useState<Set<string>>(new Set());
    // Remember which mode a popup belongs to, so switching tabs closes it.
    const [openWord, setOpenWord] = useState<{ mode: DemoMode; id: string } | null>(null);
    const [touched, setTouched] = useState(false);
    const reduceMotion = useReducedMotion();
    const [autoplay, setAutoplay] = useState(true);
    const playing = autoplay && !reduceMotion;
    const stageRef = useRef<HTMLDivElement>(null);
    const cursor = useAutoplay({ mode, enabled: playing, stageRef, setOpenWord, setAdded });
    // Any interaction hands control to the visitor; after RESUME_AFTER_MS
    // without one, the autoplay starts again from a clean state.
    const resumeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    useEffect(() => () => clearTimeout(resumeTimer.current ?? undefined), []);
    const takeOver = () => {
        if (reduceMotion) return;
        if (playing) {
            setAutoplay(false);
            setAdded(new Set());
            setOpenWord(null);
        }
        clearTimeout(resumeTimer.current ?? undefined);
        resumeTimer.current = setTimeout(() => {
            setAdded(new Set());
            setOpenWord(null);
            setAutoplay(true);
        }, RESUME_AFTER_MS);
    };
    const open = openWord?.mode === mode ? openWord.id : null;
    const setOpen = (id: string | null) => setOpenWord(id ? { mode, id } : null);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpenWord(null);
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

    const props: StageProps = {
        added,
        open,
        hinted: touched || playing ? null : FIRST_WORD[mode],
        onOpen: (id) => {
            setOpen(id);
            setTouched(true);
        },
        onClose: () => setOpen(null),
        onAdd: (id) => {
            setAdded((prev) => new Set(prev).add(id));
            setTimeout(() => setOpenWord((cur) => (cur?.id === id ? null : cur)), 900);
        },
    };

    const total = (mode === 'video' ? SUBTITLE : [...ARTICLE, ...ARTICLE_2]).filter(isWord).length;

    return (
        <div
            onPointerDown={takeOver}
            // Browsers send a synthetic move with no delta when the page scrolls
            // under a resting mouse; only real movement counts as taking over.
            onPointerMove={(e) => (e.movementX || e.movementY) && takeOver()}
            onFocusCapture={takeOver}
        >
            <div className="overflow-hidden rounded-2xl bg-white shadow-[0_24px_60px_-24px_rgba(15,23,42,0.35)] ring-1 ring-gray-900/[0.07]">
                <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-2.5">
                    <div className="flex gap-1.5">
                        <span className="h-2.5 w-2.5 rounded-full bg-gray-200" />
                        <span className="h-2.5 w-2.5 rounded-full bg-gray-200" />
                        <span className="h-2.5 w-2.5 rounded-full bg-gray-200" />
                    </div>
                    <div className="mx-auto w-full max-w-xs truncate rounded-md bg-gray-50 px-3 py-1 text-center text-[11px] text-gray-400">
                        {mode === 'video' ? 'youtube.com/watch' : 'elpais.com/example'}
                    </div>
                    <div className="w-[42px]" />
                </div>
                <div
                    ref={stageRef}
                    className={`relative ${
                        mode === 'video' ? 'h-[clamp(240px,34vh,340px)]' : 'h-[clamp(320px,50vh,460px)]'
                    }`}
                >
                    {/* Crossfade: both stages overlap for a moment, so the frame is never empty. */}
                    <AnimatePresence initial={false}>
                        <motion.div
                            key={mode}
                            className="absolute inset-0"
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            transition={{ duration: 0.3, ease: 'easeOut' }}
                        >
                            {mode === 'video' ? <VideoStage {...props} /> : <ReaderStage {...props} />}
                        </motion.div>
                    </AnimatePresence>
                    <FakeCursor cursor={cursor} />
                </div>
            </div>

            <div className="mt-3 flex h-5 items-center justify-between text-xs text-gray-500">
                <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                        key={added.size > 0 && !playing ? 'done' : 'hint'}
                        initial={{ opacity: 0, y: 3 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -3 }}
                        transition={{ duration: 0.15 }}
                    >
                        {added.size === 0 || playing
                            ? playing
                                ? 'Move your mouse here or tap to try it yourself.'
                                : 'Hover or tap a highlighted word.'
                            : added.size === total
                              ? 'All added.'
                              : 'Added to your flashcards.'}
                    </motion.span>
                </AnimatePresence>
                {added.size > 0 && !playing && (
                    <button
                        type="button"
                        onClick={() => setAdded(new Set())}
                        className="inline-flex items-center gap-1 text-gray-400 hover:text-gray-600"
                    >
                        <RotateCcw size={12} />
                        Reset
                    </button>
                )}
            </div>
        </div>
    );
}
