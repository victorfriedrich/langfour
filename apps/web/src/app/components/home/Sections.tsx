'use client';

import React, { useState } from 'react';
import VideoCard, { Thumbnail } from './VideoCard';
import {
  ALL,
  LEVELS,
  minutes,
  percent,
  youtubeUrl,
  type HomeChannel,
  type HomeEmpty,
  type HomeVideo,
  type Level,
  type Shelf,
} from './homeApi';

type Open = (video: HomeVideo, event: React.MouseEvent) => void;

function ShelfRow({ title, link, onLink, shelf, language, onOpen, onHide }: {
  title: string;
  link: string;
  onLink: () => void;
  shelf: Shelf;
  language: string;
  onOpen: Open;
  onHide: (video: HomeVideo) => void;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline gap-2">
        <h3 className="text-base font-semibold leading-5 text-gray-900">{title}</h3>
        <button type="button" onClick={onLink} className="ml-auto text-sm font-medium text-indigo-600 hover:text-indigo-800">
          {link}
        </button>
      </div>
      <ul className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {shelf.videos.map((v) => (
          <VideoCard key={v.id} video={v} language={language} onOpen={onOpen} onHide={onHide} />
        ))}
      </ul>
    </section>
  );
}

/**
 * The grammar filter left nothing in this topic: where the topic starts,
 * how many videos each level has, the nearest videos and easy videos from
 * other topics (docs/plans/home-redesign.md, screen 5).
 */
export function EmptyFilters({ topic, grammar, levels, empty, language, onGrammar, onTopic, onOpen, onHide }: {
  topic: string;
  grammar: Level;
  levels: Record<Level, number>;
  empty: HomeEmpty;
  language: string;
  onGrammar: (level: Level) => void;
  onTopic: (topic: string) => void;
  onOpen: Open;
  onHide: (video: HomeVideo) => void;
}) {
  const name = topic === ALL ? 'Videos' : topic;
  const nearest = empty.nearest_level;
  const heading = nearest ? `${name} ${topic === ALL ? 'start' : 'starts'} at ${nearest}` : `No ${topic === ALL ? '' : `${topic} `}videos up to ${grammar} yet`;

  return (
    <div className="flex flex-col gap-8 pt-4">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5">
        <h2 className="text-3xl font-semibold tracking-tight text-gray-900 sm:text-[44px] sm:leading-[60px]">{heading}</h2>
        <div role="group" aria-label={`${name} at each grammar level`} className="flex gap-1">
          {LEVELS.map((level) => {
            const count = levels[level];
            const current = level === grammar;
            const style = current
              ? 'border-2 border-gray-900 bg-gray-100 text-gray-900'
              : level === nearest
                ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                : count
                  ? 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  : 'bg-gray-100 text-gray-600';
            return (
              <button
                key={level}
                type="button"
                disabled={current || !count}
                aria-pressed={current}
                onClick={() => onGrammar(level)}
                className={`flex h-[60px] w-14 flex-col items-center justify-center gap-0.5 rounded-lg sm:w-[84px] ${style}`}
              >
                <span className="text-base font-semibold leading-5">{level}</span>
                <span className="text-xs leading-4">{count.toLocaleString()}</span>
              </button>
            );
          })}
        </div>
      </div>
      {nearest && empty.nearest && (
        <ShelfRow
          title={`${name} up to ${nearest}`}
          link={`Show all ${empty.nearest.count.toLocaleString()}`}
          onLink={() => onGrammar(nearest)}
          shelf={empty.nearest}
          language={language}
          onOpen={onOpen}
          onHide={onHide}
        />
      )}
      {empty.other && (
        <ShelfRow
          title={`Other topics up to ${grammar}`}
          link={`Show all ${empty.other.count.toLocaleString()}`}
          onLink={() => onTopic(ALL)}
          shelf={empty.other}
          language={language}
          onOpen={onOpen}
          onHide={onHide}
        />
      )}
    </div>
  );
}

function ChannelRow({ channel, language, onOpen, onFollow }: {
  channel: HomeChannel;
  language: string;
  onOpen: Open;
  onFollow: (channelId: string, follow: boolean) => Promise<void>;
}) {
  const [following, setFollowing] = useState(channel.following);
  const [busy, setBusy] = useState(false);
  const { channel_id: channelId } = channel;

  const toggle = async () => {
    if (!channelId) return;
    setBusy(true);
    try {
      await onFollow(channelId, !following);
      setFollowing(!following);
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-wrap items-start gap-x-8 gap-y-4 border-b border-gray-100 py-6">
      <div className="flex w-full flex-col gap-1 sm:w-[200px] sm:flex-none">
        <span className="text-base font-semibold text-gray-900">{channel.name}</span>
        <span className="text-xs text-gray-500">
          {percent(channel.understood)} known · {channel.videos} videos
        </span>
        {channelId && (
          <button
            type="button"
            aria-pressed={following}
            disabled={busy}
            onClick={toggle}
            className="mt-3 h-9 self-start rounded-lg border border-gray-200 bg-white px-3.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {following ? 'Following' : 'Follow'}
          </button>
        )}
      </div>
      <ul lang={language} className="grid min-w-0 flex-1 basis-[560px] grid-cols-2 gap-4 sm:grid-cols-4">
        {channel.best.map((v) => (
          <li key={v.id} className="flex min-w-0 flex-col gap-2">
            <a
              href={youtubeUrl(v.id)}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => onOpen(v, e)}
              tabIndex={-1}
              aria-hidden="true"
              className="block aspect-video overflow-hidden rounded-md bg-gray-200"
            >
              <Thumbnail video={v} />
            </a>
            <a
              href={youtubeUrl(v.id)}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => onOpen(v, e)}
              className="line-clamp-2 text-sm font-medium leading-[18px] text-gray-900 hover:underline"
            >
              {v.title}
            </a>
            <span lang="en" className="text-xs text-gray-500">
              <span className="font-semibold text-gray-900">{percent(v.understood)}</span>
              {v.duration_s !== null && ` · ${minutes(v.duration_s)} min`}
            </span>
          </li>
        ))}
      </ul>
    </li>
  );
}

export function ChannelsAtYourLevel({ channels, language, onOpen, onFollow }: {
  channels: HomeChannel[];
  language: string;
  onOpen: Open;
  onFollow: (channelId: string, follow: boolean) => Promise<void>;
}) {
  return (
    <section aria-labelledby="home-channels" className="mt-12 border-t border-gray-100 pt-8">
      <h2 id="home-channels" className="mb-2 text-base font-semibold text-gray-900">
        Channels at your level
      </h2>
      <ul>
        {channels.map((c) => (
          <ChannelRow key={c.name} channel={c} language={language} onOpen={onOpen} onFollow={onFollow} />
        ))}
      </ul>
    </section>
  );
}
