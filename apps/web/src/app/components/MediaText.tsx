import React from 'react';
import type { TranscriptChunk } from '../media/api';

interface MediaTextProps {
  chunks: TranscriptChunk[];
  /** Word ids to mark as new, the reader's amber wash. */
  newIds: Set<number>;
  selectedIds: number[];
  onWordClick: (id: number) => void;
}

// A pause this long between subtitle cues starts a new paragraph.
const PARAGRAPH_GAP_SECONDS = 2;

/**
 * An item's text laid out the way the reader showed it: headings, list items
 * and quotes for articles, stanzas for songs, and episodes' cues run together
 * into paragraphs. New words can be clicked to pick them, like the list.
 */
export default function MediaText({ chunks, newIds, selectedIds, onWordClick }: MediaTextProps) {
  const words = (chunk: TranscriptChunk) => <Marked chunk={chunk} newIds={newIds} selectedIds={selectedIds} onWordClick={onWordClick} />;
  return <article className="font-serif text-lg leading-[1.7] text-gray-900 [overflow-wrap:break-word]">{groupBlocks(chunks).map((group, index) => {
    if (group.kind === 'list') return <ul key={index} className="mb-[1.1em] list-disc pl-[1.3em]">{group.chunks.map((chunk, i) => <li key={i} className="mb-[0.35em]">{words(chunk)}</li>)}</ul>;
    if (group.kind === 'cues') return <p key={index} className="mb-[1.1em]">{group.chunks.map((chunk, i) => <React.Fragment key={i}>{i > 0 && ' '}{words(chunk)}</React.Fragment>)}</p>;
    const [chunk] = group.chunks;
    switch (chunk.block) {
      case 'h2': return <h2 key={index} className="mb-[0.6em] mt-[1.6em] text-[1.3em] font-bold leading-tight">{words(chunk)}</h2>;
      case 'h3': return <h3 key={index} className="mb-[0.6em] mt-[1.6em] text-[1.12em] font-bold leading-tight">{words(chunk)}</h3>;
      case 'h4': return <h4 key={index} className="mb-[0.6em] mt-[1.6em] font-bold leading-tight">{words(chunk)}</h4>;
      case 'blockquote': return <blockquote key={index} className="my-[1.2em] border-l-[3px] border-gray-200 pl-4 text-gray-500">{words(chunk)}</blockquote>;
      case 'pre': return <pre key={index} className="mb-[1.1em] overflow-x-auto rounded-lg bg-gray-100 p-3 font-mono text-[0.85em]">{words(chunk)}</pre>;
      case 'figcaption': return <p key={index} className="mb-[1.1em] text-center font-sans text-[13px] leading-snug text-gray-500">{words(chunk)}</p>;
      // Lyrics keep their line breaks within a stanza.
      default: return <p key={index} className="mb-[1.1em] whitespace-pre-line">{words(chunk)}</p>;
    }
  })}</article>;
}

type Group = { kind: 'block' | 'list' | 'cues'; chunks: TranscriptChunk[] };

/** Consecutive list items share one list; timed cues join into paragraphs at pauses. */
export function groupBlocks(chunks: TranscriptChunk[]): Group[] {
  const groups: Group[] = [];
  chunks.forEach((chunk, index) => {
    const last = groups[groups.length - 1];
    if (chunk.timestamp) {
      const previous = chunks[index - 1]?.timestamp;
      if (last?.kind === 'cues' && previous && chunk.timestamp[0] - previous[1] < PARAGRAPH_GAP_SECONDS) last.chunks.push(chunk);
      else groups.push({ kind: 'cues', chunks: [chunk] });
    } else if (chunk.block === 'li') {
      if (last?.kind === 'list') last.chunks.push(chunk);
      else groups.push({ kind: 'list', chunks: [chunk] });
    } else {
      groups.push({ kind: 'block', chunks: [chunk] });
    }
  });
  return groups;
}

function Marked({ chunk, newIds, selectedIds, onWordClick }: { chunk: TranscriptChunk; newIds: Set<number>; selectedIds: number[]; onWordClick: (id: number) => void }) {
  const spans = (chunk.words ?? []).filter(([, , id]) => newIds.has(id));
  if (spans.length === 0) return <>{chunk.text}</>;
  const parts: React.ReactNode[] = [];
  let offset = 0;
  for (const [start, end, id] of spans) {
    if (start < offset) continue;
    parts.push(chunk.text.slice(offset, start));
    const selected = selectedIds.includes(id);
    parts.push(<span key={start} role="button" tabIndex={0} aria-pressed={selected} onClick={() => onWordClick(id)} onKeyDown={(event) => (event.key === 'Enter' || event.key === ' ') && (event.preventDefault(), onWordClick(id))}
      className={`cursor-pointer px-px ${selected ? 'rounded-sm bg-indigo-100 text-indigo-900' : 'border-b border-dashed border-[#d9a760] bg-[rgba(255,236,179,0.3)] hover:bg-[rgba(255,236,179,0.5)]'}`}>{chunk.text.slice(start, end)}</span>);
    offset = end;
  }
  parts.push(chunk.text.slice(offset));
  return <>{parts}</>;
}
