'use client';

import React, { useState } from 'react';
import VideoCard, { ROW } from './VideoCard';
import {
  ALL,
  LEVELS,
  percent,
  type ChannelBasis,
  type HomeChannel,
  type HomeEmpty,
  type HomeVideo,
  type Level,
  type Shelf,
} from './homeApi';

type Open = (video: HomeVideo, event: React.MouseEvent) => void;
type Act = (video: HomeVideo) => void;

function ShelfRow({ title, link, onLink, shelf, language, onOpen, onHide, onShowWords }: {
  title: string;
  link: string;
  onLink: () => void;
  shelf: Shelf;
  language: string;
  onOpen: Open;
  onHide: Act;
  onShowWords: Act;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline gap-2">
        <h3 className="text-base font-semibold leading-5 text-gray-900">{title}</h3>
        <button type="button" onClick={onLink} className="ml-auto text-sm font-medium text-indigo-600 hover:text-indigo-800">
          {link}
        </button>
      </div>
      <ul className={ROW}>
        {shelf.videos.map((v) => (
          <VideoCard key={v.id} video={v} language={language} onOpen={onOpen} onHide={onHide} onShowWords={onShowWords} />
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
export function EmptyFilters({ topic, grammar, levels, empty, language, onGrammar, onTopic, onOpen, onHide, onShowWords }: {
  topic: string;
  grammar: Level;
  levels: Record<Level, number>;
  empty: HomeEmpty;
  language: string;
  onGrammar: (level: Level) => void;
  onTopic: (topic: string) => void;
  onOpen: Open;
  onHide: Act;
  onShowWords: Act;
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
          onShowWords={onShowWords}
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
          onShowWords={onShowWords}
        />
      )}
    </div>
  );
}

function ChannelRow({ channel, language, onOpen, onHide, onShowWords, onFollow }: {
  channel: HomeChannel;
  language: string;
  onOpen: Open;
  onHide: Act;
  onShowWords: Act;
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
    <li className="flex flex-col gap-3">
      <div className="flex min-h-8 items-center gap-3">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
          <span className="truncate text-sm font-semibold text-gray-900">{channel.name}</span>
          <span className="text-xs text-gray-500">
            {percent(channel.understood)} known · {channel.videos} videos
            {channel.because && ` · like ${channel.because}`}
          </span>
        </div>
        {channelId && (
          <button
            type="button"
            aria-pressed={following}
            disabled={busy}
            onClick={toggle}
            className="ml-auto h-8 flex-none rounded-lg border border-gray-200 bg-white px-3 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {following ? 'Following' : 'Follow'}
          </button>
        )}
      </div>
      <ul className={ROW}>
        {channel.best.map((v) => (
          <VideoCard
            key={v.id}
            video={v}
            language={language}
            onOpen={onOpen}
            onHide={onHide}
            onShowWords={onShowWords}
            hideChannel
          />
        ))}
      </ul>
    </li>
  );
}

const list = (items: string[]) => new Intl.ListFormat('en', { type: 'conjunction' }).format(items);

/** What the picks rest on, or, with nothing yet, how to give them something. */
export function basisText(basis: ChannelBasis | null): string {
  const following = basis?.following ?? [];
  const watched = basis?.watched ?? 0;
  if (!following.length && !watched) {
    return 'Picked by how much you’d understand. To match them to what you like, follow a '
      + 'channel here or with the star on its YouTube page, or turn on YouTube history in '
      + 'the Langfour extension’s menu on YouTube.';
  }
  const shown = following.length > 3
    ? [...following.slice(0, 2), `${following.length - 2} more`]
    : following;
  const parts = [];
  if (shown.length) parts.push(`${list(shown)}, which you follow`);
  if (watched) parts.push(`${watched} ${watched === 1 ? 'video' : 'videos'} you watched`);
  return `Based on ${parts.join(', and ')}.`;
}

export function ChannelsYouMightLike({ channels, basis, topic, language, onOpen, onHide, onShowWords, onFollow }: {
  channels: HomeChannel[];
  basis: ChannelBasis | null;
  topic: string;
  language: string;
  onOpen: Open;
  onHide: Act;
  onShowWords: Act;
  onFollow: (channelId: string, follow: boolean) => Promise<void>;
}) {
  return (
    <section aria-labelledby="home-channels" className="mt-10 border-t border-gray-100 pt-8">
      <h2 id="home-channels" className="text-lg font-semibold text-gray-900">
        {topic === ALL ? 'Channels you might like' : `${topic} channels you might like`}
      </h2>
      <p className="mb-5 mt-1 text-sm text-gray-500">{basisText(basis)}</p>
      <ul className="flex flex-col gap-8">
        {channels.map((c) => (
          <ChannelRow
            key={c.name}
            channel={c}
            language={language}
            onOpen={onOpen}
            onHide={onHide}
            onShowWords={onShowWords}
            onFollow={onFollow}
          />
        ))}
      </ul>
    </section>
  );
}
