'use client';

import React, { useEffect, useRef, useState } from 'react';
import { MoreVertical } from 'lucide-react';
import { formatDuration, percent, watchedText, youtubeUrl, type HomeVideo } from './homeApi';

// Every row of cards on the page shares these columns, so a channel's row
// lines up with the grid above it. A row shows as many cards as fit in one
// line, and two on a phone.
export const GRID = 'grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';
export const ROW = `${GRID} max-lg:[&>li:nth-child(n+3)]:hidden lg:max-xl:[&>li:nth-child(n+4)]:hidden`;

export function Thumbnail({ video, className = '' }: { video: HomeVideo; className?: string }) {
  return (
    // YouTube's thumbnail; the grey shows while it loads or if it can't.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`https://i.ytimg.com/vi/${video.id}/mqdefault.jpg`}
      alt=""
      loading="lazy"
      onError={(e) => {
        e.currentTarget.style.visibility = 'hidden';
      }}
      className={`h-full w-full object-cover ${className}`}
    />
  );
}

function CardMenu({ items }: { items: [string, () => void][] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative -mr-1.5 -mt-1 shrink-0">
      <button
        type="button"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex h-7 w-7 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-800"
      >
        <MoreVertical size={16} aria-hidden="true" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-8 z-20 min-w-40 rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
        >
          {items.map(([label, act]) => (
            <button
              key={label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                act();
              }}
              className="block w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface CardProps {
  video: HomeVideo;
  language: string;
  onOpen: (video: HomeVideo, event: React.MouseEvent) => void;
  onHide?: (video: HomeVideo) => void;
  onShowWords?: (video: HomeVideo) => void;
  /** In a channel's own row, where the name is already above. */
  hideChannel?: boolean;
}

/**
 * A video in the grid. The badge widens to "96% · 14 new words" on hover;
 * where nothing hovers, the new words go in the line under the title.
 */
export default function VideoCard({ video, language, onOpen, onHide, onShowWords, hideChannel = false }: CardProps) {
  const href = youtubeUrl(video.id);
  const started = video.watched_share !== null;
  const meta = [!hideChannel && video.channel, started && watchedText(video.watched_share!, video.duration_s)].filter(Boolean);
  const newWords = `${video.new_words} new ${video.new_words === 1 ? 'word' : 'words'}`;

  return (
    <li className="group flex min-w-0 flex-col gap-2">
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        onClick={(e) => onOpen(video, e)}
        tabIndex={-1}
        aria-hidden="true"
        className="relative block aspect-video overflow-hidden rounded-lg bg-gray-200"
      >
        <Thumbnail video={video} />
        <span
          className={`absolute left-1.5 rounded bg-white px-1.5 py-0.5 text-xs font-semibold text-gray-900 ${
            started ? 'bottom-2.5' : 'bottom-1.5'
          }`}
        >
          {percent(video.understood)}
          <span className="hidden [@media(hover:hover)]:group-hover:inline"> · {newWords}</span>
        </span>
        {video.duration_s !== null && (
          <span
            className={`absolute right-1.5 rounded bg-black/75 px-1.5 py-0.5 text-xs font-medium text-white ${
              started ? 'bottom-2.5' : 'bottom-1.5'
            }`}
          >
            {formatDuration(video.duration_s)}
          </span>
        )}
        {started && (
          <span className="absolute inset-x-0 bottom-0 h-1 bg-white/55">
            <span className="block h-1 bg-indigo-600" style={{ width: `${Math.round(video.watched_share! * 100)}%` }} />
          </span>
        )}
      </a>
      <div className="flex items-start gap-1">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            lang={language}
            onClick={(e) => onOpen(video, e)}
            className="line-clamp-2 text-sm font-medium leading-5 text-gray-900 hover:underline"
          >
            {video.title}
          </a>
          <span className="text-xs leading-4 text-gray-500">
            {meta.join(' · ')}
            <span className="hidden [@media(hover:none)]:inline">
              {meta.length ? ' · ' : ''}
              {newWords}
            </span>
          </span>
        </div>
        {(onShowWords || onHide) && (
          <CardMenu
            items={[
              ...(onShowWords ? [['Show words', () => onShowWords(video)] as [string, () => void]] : []),
              ...(onHide ? [['Not interested', () => onHide(video)] as [string, () => void]] : []),
            ]}
          />
        )}
      </div>
    </li>
  );
}
