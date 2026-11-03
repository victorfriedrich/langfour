'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ChevronDown, Loader2, Search } from 'lucide-react';
import { useHome } from '../../hooks/useHome';
import { useExtensionStatus } from '../../hooks/useExtensionStatus';
import { useWatchedVideos } from '../../hooks/useWatchedVideos';
import VideoCard, { Thumbnail } from './VideoCard';
import { ChannelsAtYourLevel, EmptyFilters } from './Sections';
import { ExtensionPrompt, Pill, PillButton, PillText } from './Overlays';
import {
  ALL,
  DEFAULT_FILTERS,
  FOLLOWING,
  LENGTHS,
  LEVELS,
  WATCHED,
  peekAway,
  saveAway,
  shortTitle,
  takeAway,
  youtubeUrl,
  type HomeFilters,
  type HomeVideo,
  type LengthBand,
  type Level,
} from './homeApi';

const PAGE = 12;
// Back sooner than this, the learner only glanced at the tab.
const MIN_AWAY_MS = 15_000;
const HIDDEN_PILL_MS = 8_000;
const PROMPTED_KEY = 'langfour-extension-prompted';
const grammarKey = (language: string) => `langfour-home-grammar-${language}`;

type PillState =
  | { kind: 'hidden'; video: HomeVideo; scope: 'video' | 'channel' }
  | { kind: 'saved'; count: number; title: string };

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Storage off: the choice lasts for this visit only.
  }
}

function FilterSelect<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <label className="relative inline-flex h-9 items-center">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="h-9 cursor-pointer appearance-none rounded-lg border border-gray-200 bg-white pl-3.5 pr-8 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
      >
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
      <ChevronDown size={14} aria-hidden="true" className="pointer-events-none absolute right-3 text-gray-500" />
    </label>
  );
}

function WatchedList({ language }: { language: string }) {
  const { videos, error, unmark } = useWatchedVideos(true);
  if (error) return <p className="py-8 text-center text-red-500">{error}</p>;
  if (videos === null) return <Loader2 className="mx-auto my-8 h-6 w-6 animate-spin text-indigo-500" />;
  if (videos.length === 0) return <p className="py-8 text-center text-gray-500">No watched videos yet</p>;
  return (
    <ul className="grid grid-cols-1 gap-x-5 gap-y-8 sm:grid-cols-[repeat(auto-fill,minmax(240px,1fr))]">
      {videos.map((video) => (
        <li key={video.video_id} className="flex min-w-0 flex-col gap-2.5">
          <a
            href={youtubeUrl(video.video_id)}
            target="_blank"
            rel="noreferrer"
            tabIndex={-1}
            aria-hidden="true"
            className="block aspect-video overflow-hidden rounded-lg bg-gray-200"
          >
            <Thumbnail video={{ id: video.video_id } as HomeVideo} />
          </a>
          <a
            href={youtubeUrl(video.video_id)}
            target="_blank"
            rel="noreferrer"
            lang={language}
            className="line-clamp-2 text-sm font-medium leading-5 text-gray-900 hover:underline"
          >
            {video.title ?? video.video_id}
          </a>
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">{new Date(video.watched_at).toLocaleDateString()}</span>
            <button
              type="button"
              onClick={() => unmark(video.video_id).catch((err) => console.error(err))}
              className="h-8 rounded-lg border border-gray-200 bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Unmark
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * The Videos page (docs/plans/home-redesign.md): pick a video, watch it on
 * YouTube with the extension, come back to what you saved.
 */
export default function VideoHome() {
  const [filters, setFilters] = useState<HomeFilters>(DEFAULT_FILTERS);
  const [view, setView] = useState<string>(ALL); // a topic, or WATCHED
  const [search, setSearch] = useState('');
  const { page, loading, error, reload, setHidden, setFollowing, cameBack, language } = useHome(filters);
  const [shown, setShown] = useState(PAGE);
  const [grammarFor, setGrammarFor] = useState<string | null>(null);
  const [hiddenVideos, setHiddenVideos] = useState<Set<string>>(new Set());
  const [hiddenChannels, setHiddenChannels] = useState<Set<string>>(new Set());
  const [pill, setPill] = useState<PillState | null>(null);
  const [prompt, setPrompt] = useState<HomeVideo | null>(null);
  const extension = useExtensionStatus();

  const update = useCallback((change: Partial<HomeFilters>) => {
    setFilters((f) => ({ ...f, ...change }));
    setShown(PAGE);
  }, []);

  // The grammar filter is remembered per language, read when it changes.
  if (language && grammarFor !== language) {
    setGrammarFor(language);
    const saved = stored(grammarKey(language));
    setFilters((f) => ({ ...f, grammar: LEVELS.includes(saved as Level) ? (saved as Level) : null }));
  }

  const setGrammar = (grammar: Level | null) => {
    if (language) store(grammarKey(language), grammar);
    update({ grammar });
  };

  const setTopic = (topic: string) => {
    setView(topic);
    if (topic !== WATCHED) update({ topic });
  };

  useEffect(() => {
    const id = setTimeout(() => {
      if (search !== filters.q) update({ q: search });
    }, 300);
    return () => clearTimeout(id);
  }, [search, filters.q, update]);

  const topics = page?.topics ?? [];
  const hasLevels = Boolean(page?.levels);

  // Back from YouTube: refresh how far each video got, and say what was saved.
  useEffect(() => {
    const check = () => {
      if (document.visibilityState !== 'visible') return;
      const away = peekAway();
      if (!away || Date.now() - Date.parse(away.leftAt) < MIN_AWAY_MS) return;
      takeAway();
      reload();
      cameBack(away.videoId, away.leftAt)
        .then(({ saved }) => saved > 0 && setPill({ kind: 'saved', count: saved, title: away.title }))
        .catch((err) => console.error(err));
    };
    check();
    document.addEventListener('visibilitychange', check);
    window.addEventListener('focus', check);
    return () => {
      document.removeEventListener('visibilitychange', check);
      window.removeEventListener('focus', check);
    };
  }, [cameBack, reload]);

  useEffect(() => {
    if (pill?.kind !== 'hidden') return;
    const id = setTimeout(() => setPill(null), HIDDEN_PILL_MS);
    return () => clearTimeout(id);
  }, [pill]);

  const leave = (video: HomeVideo) =>
    saveAway({ videoId: video.id, title: video.title, leftAt: new Date().toISOString() });

  const onOpen = (video: HomeVideo, event: React.MouseEvent) => {
    // Once, on a desktop browser that can take the extension.
    const desktop = typeof window !== 'undefined' && window.matchMedia?.('(hover: hover) and (pointer: fine)').matches;
    if (extension.state === 'missing' && desktop && !stored(PROMPTED_KEY)) {
      event.preventDefault();
      store(PROMPTED_KEY, '1');
      setPrompt(video);
      return;
    }
    leave(video);
  };

  const hide = (video: HomeVideo) => {
    setHiddenVideos((s) => new Set(s).add(video.id));
    setPill({ kind: 'hidden', video, scope: 'video' });
    setHidden(video.id, false, true).catch((err) => {
      console.error(err);
      setHiddenVideos((s) => {
        const next = new Set(s);
        next.delete(video.id);
        return next;
      });
      setPill(null);
    });
  };

  const hideChannel = (video: HomeVideo) => {
    if (!video.channel) return;
    setHiddenChannels((s) => new Set(s).add(video.channel!));
    setPill({ kind: 'hidden', video, scope: 'channel' });
    setHidden(video.id, true, true).catch((err) => console.error(err));
  };

  const undo = (video: HomeVideo, scope: 'video' | 'channel') => {
    setPill(null);
    const without = <T,>(s: Set<T>, item: T) => {
      const next = new Set(s);
      next.delete(item);
      return next;
    };
    if (scope === 'video') setHiddenVideos((s) => without(s, video.id));
    else setHiddenChannels((s) => without(s, video.channel!));
    setHidden(video.id, scope === 'channel', false).catch((err) => console.error(err));
  };

  const visible = useMemo(
    () => (page?.videos ?? []).filter((v) => !hiddenVideos.has(v.id) && !(v.channel && hiddenChannels.has(v.channel))),
    [page, hiddenVideos, hiddenChannels],
  );
  const channels = (page?.channels ?? []).filter((c) => !hiddenChannels.has(c.name));
  const code = language ?? 'es';
  const query = filters.q.trim();

  const content = () => {
    if (error) return <p className="py-8 text-center text-red-500">{error}</p>;
    if (!page) return <Loader2 className="mx-auto my-16 h-8 w-8 animate-spin text-indigo-500" />;
    if (visible.length === 0) {
      if (page.empty && page.levels && filters.grammar) {
        return (
          <EmptyFilters
            topic={filters.topic}
            grammar={filters.grammar}
            levels={page.levels}
            empty={page.empty}
            language={code}
            onGrammar={setGrammar}
            onTopic={setTopic}
            onOpen={onOpen}
            onHide={hide}
          />
        );
      }
      return (
        <div className="flex flex-col items-center gap-3 py-16 text-center text-gray-500">
          {filters.topic === FOLLOWING && !query ? (
            <p>Videos from the channels you follow show up here. Follow one under Channels at your level in All, or with Favourite on its YouTube page.</p>
          ) : query ? (
            <p>No videos match “{query}”.</p>
          ) : (
            <p>No more videos here.</p>
          )}
          {(filters.grammar || filters.length !== 'any' || query || filters.topic !== ALL) && (
            <button
              type="button"
              onClick={() => {
                setSearch('');
                setTopic(ALL);
                setGrammar(null);
                update({ length: 'any', q: '' });
              }}
              className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
            >
              Clear filters
            </button>
          )}
        </div>
      );
    }
    return (
      <>
        <ul className="grid grid-cols-1 gap-x-5 gap-y-8 sm:grid-cols-[repeat(auto-fill,minmax(240px,1fr))]">
          {visible.slice(0, shown).map((v) => (
            <VideoCard key={v.id} video={v} language={code} onOpen={onOpen} onHide={hide} />
          ))}
        </ul>
        {visible.length > shown && (
          <div className="mt-8 flex justify-center">
            <button
              type="button"
              onClick={() => setShown((n) => n + PAGE)}
              className="h-9 rounded-lg border border-gray-200 bg-white px-4 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Show more
            </button>
          </div>
        )}
        {filters.topic === ALL && !query && channels.length > 0 && (
          <ChannelsAtYourLevel channels={channels} language={code} onOpen={onOpen} onFollow={setFollowing} />
        )}
      </>
    );
  };

  return (
    <div className="min-h-screen bg-white px-4 pb-24 pt-6 md:px-8 md:pt-10">
      <header lang="en" className="flex flex-wrap items-center gap-3">
        <h1 className="mr-auto text-2xl font-semibold text-gray-900">Videos</h1>
        <label className="flex h-9 w-full items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 focus-within:ring-2 focus-within:ring-indigo-500 sm:w-72">
          <Search size={16} aria-hidden="true" className="text-gray-500" />
          <span className="sr-only">Search videos</span>
          <input
            type="search"
            placeholder="Search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              if (view === WATCHED) setTopic(filters.topic);
            }}
            className="min-w-0 flex-1 bg-transparent text-sm text-gray-900 outline-none placeholder:text-gray-500"
          />
        </label>
        {hasLevels && (
          <FilterSelect<string>
            label="Grammar"
            value={filters.grammar ?? ''}
            options={[['', 'Any grammar'], ...LEVELS.map((l): [string, string] => [l, `Grammar up to ${l}`])]}
            onChange={(v) => setGrammar((v || null) as Level | null)}
          />
        )}
        <FilterSelect<LengthBand>
          label="Length"
          value={filters.length}
          options={Object.entries(LENGTHS) as [LengthBand, string][]}
          onChange={(length) => update({ length })}
        />
      </header>

      <div lang="en" role="group" aria-label="Topics" className="mb-6 mt-7 flex flex-wrap gap-1">
        {[ALL, FOLLOWING, ...topics, WATCHED].map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={view === t}
            onClick={() => setTopic(t)}
            className={`h-8 rounded-full px-3 text-sm font-medium ${
              view === t ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className={loading && page ? 'opacity-60 transition-opacity' : undefined}>
        {view === WATCHED ? <WatchedList language={code} /> : content()}
      </div>

      {pill?.kind === 'hidden' && (
        <Pill>
          <PillText>
            {pill.scope === 'channel' ? `Videos from ${pill.video.channel} hidden.` : 'Hidden.'}
          </PillText>
          <PillButton onClick={() => undo(pill.video, pill.scope)}>Undo</PillButton>
          {pill.scope === 'video' && pill.video.channel && (
            <PillButton quiet onClick={() => hideChannel(pill.video)}>
              Hide all from {pill.video.channel}
            </PillButton>
          )}
        </Pill>
      )}
      {pill?.kind === 'saved' && (
        <Pill onDismiss={() => setPill(null)}>
          <PillText>
            You saved {pill.count} {pill.count === 1 ? 'word' : 'words'} from{' '}
            <span lang={code} className="font-medium">
              {shortTitle(pill.title)}
            </span>
          </PillText>
          <Link
            href="/vocabulary"
            className="inline-flex h-8 flex-none items-center rounded-full bg-white/15 px-3.5 text-sm font-medium text-white hover:bg-white/25"
          >
            See them
          </Link>
        </Pill>
      )}
      {prompt && (
        <ExtensionPrompt
          video={prompt}
          language={code}
          onClose={() => setPrompt(null)}
          onWatch={() => {
            leave(prompt);
            setPrompt(null);
          }}
        />
      )}
    </div>
  );
}
