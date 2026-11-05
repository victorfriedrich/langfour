import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { BatteryFull, Check, ChevronLeft, Ellipsis, Minimize, PanelTop, Pause, Play, Plus, RotateCw, Signal, Volume2, Wifi } from 'lucide-react';
import { ARTICLE, ARTICLE_2, SUBTITLE, WordPopup, isWord, popupMotion, type Segment, type Word } from './ExtensionDemo';

/**
 * The Safari counterpart of ExtensionDemo: hands-on imitations of the iPhone
 * extension in a phone frame. Styled after apps/extension/src/reader.css and
 * translationPopup.css at about 72% of the real size, so they match what
 * people get after installing. Taps instead of hovers, as on a real iPhone.
 */

export type SafariDemoMode = 'video' | 'reader';

const SERIF = 'ui-serif, "New York", "Iowan Old Style", Georgia, serif';

// reader.css's light theme.
const READER_THEME = {
    '--bg': '#ffffff', '--surface': '#ffffff', '--text': '#1d1d1f', '--text-2': '#6e6e73', '--line': 'rgba(0,0,0,0.1)',
    '--accent': '#4f46e5', '--bar-bg': 'rgba(255,255,255,0.82)', '--new-bg': 'rgba(255,236,179,0.3)', '--new-line': '#d9a760',
    '--active-bg': 'rgba(255,200,125,0.25)', '--active-text': '#8b4513', '--popup-word': '#5d2e0d', '--popup-rule': '#f0e9e0',
    '--popup-button': '#8b4513',
} as CSSProperties;

// Idle time after the visitor's last interaction before the autoplay resumes.
const RESUME_AFTER_MS = 10_000;
const STOPPED = Symbol('stopped');

type Touch = { x: number; y: number; pressed: boolean; visible: boolean };
type Player = {
    wait: (ms: number) => Promise<void>;
    tap: (selector: string) => Promise<void>;
};
type Demo = {
    setStage: (stage: HTMLDivElement | null) => void;
    touch: Touch;
    playing: boolean;
    handlers: { onPointerDown: () => void; onPointerMove: (e: React.PointerEvent) => void; onFocusCapture: () => void };
};

/**
 * Plays `script` on a loop while the phone is on screen, with a dot for the
 * finger. As in ExtensionDemo, any real interaction hands control to the
 * visitor, and 10 seconds without one starts it again from a clean state.
 * Both arguments must be stable. Skipped for reduced motion.
 */
function useDemoScript(script: (play: Player) => Promise<void>, reset: () => void): Demo {
    const [stage, setStage] = useState<HTMLDivElement | null>(null);
    const reduceMotion = useReducedMotion();
    const [autoplay, setAutoplay] = useState(true);
    const [touch, setTouch] = useState<Touch>({ x: 0, y: 0, pressed: false, visible: false });
    const playing = autoplay && !reduceMotion;

    useEffect(() => {
        if (!playing || !stage) return;

        let cancelled = false;
        let visible = false;
        const observer = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting), { threshold: 0.6 });
        observer.observe(stage);

        const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
        // Every step passes through here, so stopping the script takes one check.
        const wait = async (ms: number) => {
            await pause(ms);
            while (!visible && !cancelled) await pause(300);
            if (cancelled) throw STOPPED;
        };
        const tap = async (selector: string) => {
            const target = stage.querySelector(selector);
            if (!target) return;
            const t = target.getBoundingClientRect();
            const s = stage.getBoundingClientRect();
            setTouch((c) => ({ ...c, x: t.left - s.left + t.width / 2, y: t.top - s.top + t.height / 2, visible: true }));
            await wait(750);
            setTouch((c) => ({ ...c, pressed: true }));
            await wait(130);
            setTouch((c) => ({ ...c, pressed: false }));
        };

        (async () => {
            await wait(600);
            for (;;) {
                reset();
                await script({ wait, tap });
                await wait(1400);
            }
        })().catch((error) => {
            if (error !== STOPPED) throw error;
        });

        return () => {
            cancelled = true;
            observer.disconnect();
            setTouch((c) => ({ ...c, visible: false, pressed: false }));
        };
    }, [playing, stage, script, reset]);

    const resumeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    useEffect(() => () => clearTimeout(resumeTimer.current ?? undefined), []);
    const takeOver = () => {
        if (reduceMotion) return;
        if (playing) {
            setAutoplay(false);
            reset();
        }
        clearTimeout(resumeTimer.current ?? undefined);
        resumeTimer.current = setTimeout(() => {
            reset();
            setAutoplay(true);
        }, RESUME_AFTER_MS);
    };

    return {
        setStage,
        touch,
        playing,
        handlers: {
            onPointerDown: takeOver,
            // Browsers send a synthetic move with no delta when the page scrolls
            // under a resting mouse; only real movement counts as taking over.
            onPointerMove: (e) => {
                if (e.movementX || e.movementY) takeOver();
            },
            onFocusCapture: takeOver,
        },
    };
}

function Finger({ touch }: { touch: Touch }) {
    const move = { duration: 0.6, ease: [0.4, 0, 0.2, 1] as const };
    return (
        <AnimatePresence>
            {touch.visible && (
                <motion.div
                    aria-hidden
                    className="pointer-events-none absolute left-0 top-0 z-40 -ml-3.5 -mt-3.5 h-7 w-7 rounded-full bg-gray-900/30 ring-2 ring-white/80"
                    initial={{ opacity: 0, x: touch.x, y: touch.y }}
                    animate={{ opacity: 1, x: touch.x, y: touch.y, scale: touch.pressed ? 0.78 : 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ x: move, y: move, scale: { duration: 0.1 }, opacity: { duration: 0.25 } }}
                />
            )}
        </AnimatePresence>
    );
}

/** The phone and the line under it, as ExtensionDemo has under its window. */
function Phone({ setStage, touch, playing, handlers, hint, landscape, children }: Demo & { hint: string; landscape?: boolean; children: ReactNode }) {
    return (
        <div {...handlers}>
            <div
                className={`relative max-w-full bg-gray-900 p-[7px] shadow-[0_24px_60px_-24px_rgba(15,23,42,0.45)] ${
                    landscape ? 'h-[clamp(240px,42vw,340px)] w-full rounded-[2.5rem]' : 'h-[590px] w-[290px] rounded-[2.75rem]'
                }`}
            >
                <div ref={setStage} className={`relative h-full w-full overflow-hidden bg-white [isolation:isolate] ${landscape ? 'rounded-[2.1rem]' : 'rounded-[2.35rem]'}`}>
                    {children}
                    <div
                        aria-hidden
                        className={`pointer-events-none absolute z-30 rounded-full bg-black ${
                            landscape ? 'left-2 top-1/2 h-[68px] w-[20px] -translate-y-1/2' : 'left-1/2 top-2.5 h-[20px] w-[68px] -translate-x-1/2'
                        }`}
                    />
                    <div
                        aria-hidden
                        className={`pointer-events-none absolute bottom-1.5 left-1/2 z-30 h-1 -translate-x-1/2 rounded-full ${landscape ? 'w-32 bg-white/70' : 'w-24 bg-gray-400'}`}
                    />
                    <Finger touch={touch} />
                </div>
            </div>
            <p className="mt-3 h-5 text-xs text-gray-500">{playing ? 'Move your mouse here or tap to try it yourself.' : hint}</p>
        </div>
    );
}

// The same marks as reader.css: a wash and dashed line for new words, a solid
// line for words being learned.
function wordMarks(saved: boolean, active: boolean) {
    if (active) return 'bg-[var(--active-bg)] text-[color:var(--active-text)]';
    return saved
        ? 'border-b-[1.5px] border-solid border-[color:var(--new-line)]'
        : 'bg-[var(--new-bg)] border-b border-dashed border-[color:var(--new-line)] px-px';
}

function ArticleText({ segments, saved, open, onTap }: { segments: Segment[]; saved: Set<string>; open: string | null; onTap: (id: string) => void }) {
    return (
        <p className="mb-3">
            {segments.map((seg, i) =>
                isWord(seg) ? (
                    <button
                        key={seg.id}
                        type="button"
                        data-word={seg.id}
                        onClick={(e) => {
                            e.stopPropagation();
                            onTap(seg.id);
                        }}
                        className={`inline rounded-[3px] transition-colors duration-200 ${wordMarks(saved.has(seg.id), open === seg.id)}`}
                    >
                        {seg.text}
                    </button>
                ) : (
                    <span key={i}>{seg}</span>
                ),
            )}
        </p>
    );
}

function ReaderDemo() {
    const [open, setOpen] = useState<string | null>(null);
    const [saved, setSaved] = useState<Set<string>>(new Set());
    const reset = useCallback(() => {
        setOpen(null);
        setSaved(new Set());
    }, []);
    const script = useCallback(async (play: Player) => {
        for (const id of ['despierta', 'charlan', 'rincon']) {
            await play.wait(500);
            await play.tap(`[data-word="${id}"]`);
            setOpen(id);
            await play.wait(1100);
            await play.tap('[data-add]');
            setOpen(null);
            setSaved((prev) => new Set(prev).add(id));
            await play.wait(700);
        }
        await play.wait(1200);
    }, []);
    const demo = useDemoScript(script, reset);

    const word = [...ARTICLE, ...ARTICLE_2].filter(isWord).find((w) => w.id === open) ?? null;
    const glass = 'bg-[var(--bar-bg)] shadow-[0_2px_12px_rgba(0,0,0,0.14)] ring-[0.5px] ring-[color:var(--line)] backdrop-blur-xl';

    return (
        <Phone {...demo} hint={saved.size ? 'Added to your flashcards.' : 'Tap a highlighted word.'}>
            <div style={READER_THEME} onClick={() => setOpen(null)} className="absolute inset-0 overflow-hidden bg-[var(--bg)] text-[color:var(--text)]">
                <div style={{ fontFamily: SERIF }}>
                    <div aria-hidden className="flex h-[42px] items-end justify-between px-6 pb-1 font-sans text-[12px] font-semibold">
                        <span className="tabular-nums">9:41</span>
                        <span className="flex items-center gap-1">
                            <Signal size={12} strokeWidth={2.5} />
                            <Wifi size={12} strokeWidth={2.5} />
                            <BatteryFull size={15} />
                        </span>
                    </div>
                    <div aria-hidden className="flex h-9 items-center justify-between border-b-[0.5px] border-[color:var(--line)] px-1.5 font-sans">
                        <span className="flex items-center text-[13px] text-[color:var(--accent)]">
                            <ChevronLeft size={16} strokeWidth={2.4} />
                            elpais.com
                        </span>
                        <span className="flex items-center gap-2.5 pr-2">
                            <span style={{ fontFamily: SERIF }} className="rounded-sm border-b border-dashed border-[color:var(--new-line)] bg-[var(--new-bg)] px-0.5 text-[13px] leading-tight">abc</span>
                            <span className="flex items-baseline gap-px font-semibold leading-none text-[color:var(--accent)]">
                                <span className="text-[10px]">A</span>
                                <span className="text-[15px]">A</span>
                            </span>
                        </span>
                    </div>
                    <div className="px-[18px] pt-4 text-[14.5px] leading-[1.7]">
                        <h3 className="mb-3.5 text-[1.45em] font-bold leading-[1.18] tracking-[-0.01em]">La ciudad que nunca duerme</h3>
                        <ArticleText segments={ARTICLE} saved={saved} open={open} onTap={setOpen} />
                        <ArticleText segments={ARTICLE_2} saved={saved} open={open} onTap={setOpen} />
                    </div>
                </div>

                <AnimatePresence>
                    {word && (
                        <motion.div
                            initial={{ y: '100%' }}
                            animate={{ y: 0 }}
                            exit={{ y: '100%' }}
                            transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
                            onClick={(e) => e.stopPropagation()}
                            style={{ fontFamily: SERIF }}
                            className="absolute inset-x-0 bottom-0 z-20 rounded-t-[18px] bg-[var(--surface)] pb-[66px] shadow-[0_-8px_30px_rgba(0,0,0,0.14)]"
                        >
                            <div aria-hidden className="mx-auto mb-0.5 mt-1.5 h-1 w-7 rounded-full bg-[var(--line)]" />
                            <WordSheet
                                word={word}
                                saved={saved.has(word.id)}
                                onAdd={() => {
                                    setOpen(null);
                                    setSaved((prev) => new Set(prev).add(word.id));
                                }}
                            />
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Safari's floating bottom bar. */}
                <div aria-hidden className="absolute inset-x-0 bottom-0 z-[25] flex items-center gap-1.5 px-2.5 pb-4 font-sans">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${glass}`}>
                        <ChevronLeft size={18} />
                    </span>
                    <div className={`flex h-9 min-w-0 flex-1 items-center gap-1 rounded-full px-2.5 ${glass}`}>
                        <PanelTop size={15} />
                        <span className="min-w-0 flex-1 truncate text-center text-[12px]">Langfour Reader</span>
                        <RotateCw size={13} />
                    </div>
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${glass}`}>
                        <Ellipsis size={18} />
                    </span>
                </div>
            </div>
        </Phone>
    );
}

function WordSheet({ word, saved, onAdd }: { word: Word; saved: boolean; onAdd: () => void }) {
    return (
        <>
            <div className="flex items-center gap-1 px-4 pb-0.5 pt-2 text-[20px] font-bold text-[color:var(--popup-word)]">
                {word.lemma ? `${word.text} (${word.lemma})` : word.text}
                <Volume2 aria-hidden size={15} className="ml-0.5 opacity-70" />
            </div>
            <div className="px-4 pb-2.5 pt-0.5 text-[14.5px] leading-[1.4]">
                {word.translation.split(',').map((t, i) => (
                    <span key={t} className={`block ${i ? 'mt-1 border-t border-[color:var(--popup-rule)] pt-1' : ''}`}>{t.trim()}</span>
                ))}
            </div>
            {!saved && (
                <div className="px-4 pb-1">
                    <button type="button" data-add onClick={onAdd} className="w-full rounded-[10px] bg-[var(--popup-button)] py-2.5 text-[14px] text-white hover:bg-[#7a3c10]">
                        Add to flashcards
                    </button>
                </div>
            )}
        </>
    );
}

function VideoDemo() {
    const [open, setOpen] = useState<string | null>(null);
    const [saved, setSaved] = useState<Set<string>>(new Set());
    const reduceMotion = useReducedMotion();
    const reset = useCallback(() => {
        setOpen(null);
        setSaved(new Set());
    }, []);
    const script = useCallback(async (play: Player) => {
        await play.wait(900);
        for (const id of ['aprender', 'idioma']) {
            await play.tap(`[data-word="${id}"]`);
            setOpen(id);
            await play.wait(1000);
            await play.tap(`[data-add="${id}"]`);
            setSaved((prev) => new Set(prev).add(id));
            await play.wait(1000);
            await play.tap('[data-video-bg]');
            setOpen(null);
            await play.wait(1100);
        }
    }, []);
    const demo = useDemoScript(script, reset);

    // Opening a word pauses the video; closing it plays on.
    const paused = open !== null;
    const motionStyle = (animation: string): CSSProperties =>
        reduceMotion ? {} : { animation, animationPlayState: paused ? 'paused' : 'running' };
    const hint = open ? 'Tap anywhere to play on.' : saved.size ? 'Added to your flashcards.' : 'Tap a highlighted word.';

    return (
        <Phone {...demo} hint={hint} landscape>
            <style>{`
                @keyframes safari-demo-drift { to { transform: translate(36px, 22px); } }
                @keyframes safari-demo-progress { from { width: 18%; } to { width: 64%; } }
            `}</style>
            <div data-popup-bounds data-video-bg className="absolute inset-0 overflow-clip bg-[#0b0d14]" onClick={() => setOpen(null)}>
                {/* An abstract "scene" in place of real footage. */}
                <div className="absolute -left-[10%] top-[5%] h-[70%] w-[55%] rounded-full bg-indigo-500/45 blur-[70px]" style={motionStyle('safari-demo-drift 9s ease-in-out infinite alternate')} />
                <div className="absolute right-[-5%] top-[-10%] h-[60%] w-[45%] rounded-full bg-amber-400/25 blur-[80px]" style={motionStyle('safari-demo-drift 11s ease-in-out infinite alternate-reverse')} />
                <div className="absolute bottom-[-20%] left-[35%] h-[55%] w-[40%] rounded-full bg-rose-500/25 blur-[80px]" style={motionStyle('safari-demo-drift 13s ease-in-out infinite alternate')} />
                <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,rgba(0,0,0,0.55))]" />

                <div className="absolute inset-x-0 bottom-[22%] z-10 flex justify-center px-10">
                    <p className="max-w-[90%] rounded-sm bg-black/70 px-3 py-1 text-center font-sans text-[15px] leading-snug text-white md:text-[17px]">
                        {SUBTITLE.map((seg, i) =>
                            isWord(seg) ? (
                                <span key={seg.id} className="relative inline-block">
                                    <button
                                        type="button"
                                        data-word={seg.id}
                                        aria-expanded={open === seg.id}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            // A second tap on the same word closes it and plays on.
                                            setOpen((cur) => (cur === seg.id ? null : seg.id));
                                        }}
                                        className={`transition-colors duration-100 ${open === seg.id ? 'text-[#e0a87d]' : saved.has(seg.id) ? '' : 'text-[#ffb732]'}`}
                                    >
                                        {seg.text}
                                    </button>
                                    <AnimatePresence>
                                        {open === seg.id && (
                                            <WordPopup mode="video">
                                                <motion.span {...popupMotion} onClick={(e) => e.stopPropagation()} className="block origin-bottom">
                                                    <CaptionCard
                                                        word={seg}
                                                        saved={saved.has(seg.id)}
                                                        onAdd={() => setSaved((prev) => new Set(prev).add(seg.id))}
                                                    />
                                                </motion.span>
                                            </WordPopup>
                                        )}
                                    </AnimatePresence>
                                </span>
                            ) : (
                                <span key={i}>{seg}</span>
                            ),
                        )}
                    </p>
                </div>

                <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 px-10 pb-5">
                    <div className="flex items-center gap-3 text-white/80">
                        {paused ? <Play size={13} fill="currentColor" /> : <Pause size={13} fill="currentColor" />}
                        <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-white/20">
                            <div className="h-full w-[32%] rounded-full bg-white/85" style={motionStyle('safari-demo-progress 40s linear infinite')} />
                        </div>
                        <Minimize size={14} />
                    </div>
                </div>
            </div>
        </Phone>
    );
}

// .sub-tr-popup: the dictionary form over the translation, with a solid "+".
function CaptionCard({ word, saved, onAdd }: { word: Word; saved: boolean; onAdd: () => void }) {
    return (
        <span className="flex w-max min-w-[180px] items-center gap-3 rounded-[14px] border-[0.5px] border-white/10 bg-[#2c2c2e] py-2 pl-3.5 pr-2 text-left font-sans shadow-[0_10px_40px_rgba(0,0,0,0.5)]">
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-[17px] font-bold leading-tight text-[#e5e5ea]">{word.lemma ?? word.text}</span>
                <span className="text-[14px] leading-snug text-[#98989f]">{word.translation}</span>
            </span>
            <button
                type="button"
                data-add={word.id}
                onClick={onAdd}
                disabled={saved}
                aria-label={saved ? 'Added to flashcards' : 'Add to flashcards'}
                className={`grid h-9 w-9 shrink-0 place-items-center rounded-[10px] text-[#1c1c1e] transition-colors ${saved ? 'bg-[#22c55e]' : 'bg-[#a5b4fc] hover:bg-[#b6c2fd]'}`}
            >
                {saved ? <Check size={17} strokeWidth={3} /> : <Plus size={18} strokeWidth={2.5} />}
            </button>
        </span>
    );
}

export default function SafariDemo({ mode }: { mode: SafariDemoMode }) {
    return mode === 'video' ? <VideoDemo /> : <ReaderDemo />;
}
