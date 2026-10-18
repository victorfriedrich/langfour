import { describe, expect, it } from 'vitest';
import { parseTranscript } from './transcript';

describe('parseTranscript', () => {
  it('reads a Netling .whisper.json (segments with start/end)', () => {
    const parsed = parseTranscript({
      model: 'whisper-large-v3-turbo', language: 'es', timebase: 'capture', audio_seconds: 3701.016, source: 'deepinfra-api',
      chunk_boundaries: [0, 600],
      segments: [{ start: 0.42, end: 1.32, text: 'Gracias.' }, { start: 1.5, end: 3, text: ' ¿Qué? ' }],
    });
    expect(parsed.chunks).toEqual([{ timestamp: [0.42, 1.32], text: 'Gracias.' }, { timestamp: [1.5, 3], text: '¿Qué?' }]);
    expect(parsed).toMatchObject({ language: 'es', model: 'whisper-large-v3-turbo', timebase: 'capture', audioSeconds: 3701.016, dropped: 0, adjusted: 0 });
  });

  it('reads the episode details Netling writes', () => {
    const parsed = parseTranscript({ media: { type: 'series', series: 'Ozark', season: 1, episode: 3, title: 'Sugarwood', netflix_id: '81254461' }, segments: [{ start: 0, end: 1, text: 'Hola' }] });
    expect(parsed.details).toEqual({ series: 'Ozark', season: 1, episode: 3, title: 'Sugarwood' });
    expect(parseTranscript({ segments: [{ start: 0, end: 1, text: 'Hola' }] }).details).toBeNull();
  });

  it('still reads the older chunks/timestamp export', () => {
    const parsed = parseTranscript({ language: 'spanish', chunks: [{ timestamp: [0, 37.68], text: ' La Iglesia' }] });
    expect(parsed.chunks).toEqual([{ timestamp: [0, 37.68], text: 'La Iglesia' }]);
    expect(parsed.language).toBe('spanish');
  });

  it('clamps overlapping lines instead of failing, and sorts them', () => {
    const parsed = parseTranscript({ segments: [{ start: 5, end: 6, text: 'b' }, { start: 0, end: 5.37, text: 'a' }] });
    expect(parsed.chunks).toEqual([{ timestamp: [0, 5.37], text: 'a' }, { timestamp: [5.37, 6], text: 'b' }]);
    expect(parsed.adjusted).toBe(1);
  });

  it('drops lines without text and fills a missing end', () => {
    const parsed = parseTranscript([{ start: 0, end: 1, text: '  ' }, { timestamp: [2, null], text: 'hola' }]);
    expect(parsed.chunks).toEqual([{ timestamp: [2, 4], text: 'hola' }]);
    expect(parsed.dropped).toBe(1);
  });

  it('explains what it expected when no lines are found', () => {
    expect(() => parseTranscript({ cues: [] })).toThrow(/segments/);
    expect(() => parseTranscript({ segments: [{ start: 0, end: 1, text: '' }] })).toThrow(/no lines/);
  });
});
