'use client';

import React, { useEffect, useRef } from 'react';
import Link from 'next/link';
import { X } from 'lucide-react';
import { Thumbnail } from './VideoCard';
import { percent, youtubeUrl, type HomeVideo } from './homeApi';

/**
 * The first video opened without the extension: what it adds, once, and the
 * video anyway (docs/plans/home-redesign.md, screen 2).
 */
export function ExtensionPrompt({ video, language, onClose, onWatch }: {
  video: HomeVideo;
  language: string;
  onClose: () => void;
  onWatch: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-gray-900/45 px-4 pt-24 sm:pt-36" onClick={onClose}>
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="home-extension-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="flex w-full max-w-[460px] flex-col gap-5 rounded-2xl bg-white p-6 shadow-2xl outline-none"
      >
        <div className="flex items-center gap-3">
          <span className="aspect-video w-[104px] flex-none overflow-hidden rounded-md bg-gray-200">
            <Thumbnail video={video} />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span lang={language} className="line-clamp-2 text-sm font-medium leading-5 text-gray-900">
              {video.title}
            </span>
            <span className="text-xs text-gray-500">
              {[video.channel, `${percent(video.understood)} known`].filter(Boolean).join(' · ')}
            </span>
          </span>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex h-8 w-8 flex-none items-center justify-center self-start rounded-md text-gray-500 hover:bg-gray-100"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="flex flex-col gap-2.5">
          <h2 id="home-extension-title" className="text-base font-semibold text-gray-900">
            Watch it with Langfour on YouTube
          </h2>
          <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm leading-6 text-gray-700">
            <li>
              The {video.new_words} {video.new_words === 1 ? 'word' : 'words'} you don&apos;t know light up in the subtitles
            </li>
            <li>Hover a word to see what it means</li>
            <li>Words you save go straight to Practice</li>
          </ul>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href="/extension"
            className="inline-flex h-9 items-center rounded-lg bg-indigo-600 px-3.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Add to Chrome
          </Link>
          <a
            href={youtubeUrl(video.id)}
            target="_blank"
            rel="noreferrer"
            onClick={onWatch}
            className="inline-flex h-9 items-center rounded-lg border border-gray-200 bg-white px-3.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Watch without it
          </a>
        </div>
      </div>
    </div>
  );
}

/** The dark pill at the bottom: Not interested's Undo, or what was saved on YouTube. */
export function Pill({ children, onDismiss }: { children: React.ReactNode; onDismiss?: () => void }) {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4 md:bottom-8">
      <div
        role="status"
        className="pointer-events-auto flex max-w-full items-center gap-1.5 rounded-full bg-gray-900 py-1.5 pl-[18px] pr-1.5 shadow-[0_12px_32px_rgba(17,24,39,0.3)]"
      >
        {children}
        {onDismiss && (
          <button
            type="button"
            aria-label="Dismiss"
            onClick={onDismiss}
            className="flex h-8 w-8 flex-none items-center justify-center rounded-full text-gray-300 hover:bg-white/10"
          >
            <X size={16} aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
}

export function PillText({ children }: { children: React.ReactNode }) {
  return <span className="mr-2 truncate text-sm text-white">{children}</span>;
}

export function PillButton({ children, onClick, quiet = false }: {
  children: React.ReactNode;
  onClick: () => void;
  quiet?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`h-8 flex-none whitespace-nowrap rounded-full px-3.5 text-sm font-medium ${
        quiet ? 'text-indigo-200 hover:bg-white/10' : 'bg-white/15 text-white hover:bg-white/25'
      }`}
    >
      {children}
    </button>
  );
}
