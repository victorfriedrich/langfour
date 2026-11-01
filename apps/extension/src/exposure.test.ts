import { describe, expect, it } from 'vitest';
import { CAPTION_TICKS, CaptionWords, ExposureQueue, mediaKey, msToRead, tokensOf } from './exposure';

describe('tokensOf', () => {
  it('splits on everything but letters', () => {
    expect(tokensOf('¿Qué tal? l\'homme, 4K niño')).toEqual(['Qué', 'tal', 'l', 'homme', 'K', 'niño']);
  });
});

describe('mediaKey', () => {
  it('keys a YouTube video by its id, whichever URL shows it', () => {
    expect(mediaKey('https://www.youtube.com/watch?v=abc123&t=42s')).toBe('youtube:abc123');
    expect(mediaKey('https://m.youtube.com/watch?v=abc123')).toBe('youtube:abc123');
    expect(mediaKey('https://www.youtube.com/shorts/xyz')).toBe('youtube:xyz');
  });

  it('keys other pages without query or fragment', () => {
    expect(mediaKey('https://www.netflix.com/watch/8123?trackId=1')).toBe('https://www.netflix.com/watch/8123');
    expect(mediaKey('https://elpais.com/a/b.html#comments')).toBe('https://elpais.com/a/b.html');
  });
});

describe('msToRead', () => {
  it('gives a paragraph its words at a fast pace, and at least a second', () => {
    expect(msToRead(100)).toBe(15_000);
    expect(msToRead(2)).toBe(1000);
  });
});

describe('CaptionWords', () => {
  it('counts a word once it stayed on screen long enough, once per video', () => {
    const words = new CaptionWords();
    expect(words.sample(['hola', 'amigo'])).toEqual([]);
    for (let i = 2; i < CAPTION_TICKS; i++) words.sample(['hola', 'amigo']);
    expect(words.sample(['hola', 'amigo', 'nuevo'])).toEqual(['hola', 'amigo']);
    // The same word in a later line doesn't count again.
    words.sample(['hola']);
    expect(words.sample(['hola'])).toEqual([]);
    words.reset();
    words.sample(['hola']);
    expect(words.sample(['hola'])).toEqual(['hola']);
  });

  it('counts nothing for words that flashed by or were on screen while paused', () => {
    const words = new CaptionWords();
    words.sample(['rápido']);
    expect(words.sample(['otro'])).toEqual([]);
    words.sample(['pausa']);
    words.interrupt();
    expect(words.sample(['pausa'])).toEqual([]);
  });
});

describe('ExposureQueue', () => {
  it('collects words per media and empties when taken', () => {
    const queue = new ExposureQueue();
    queue.add('youtube:a', ['hola', 'perro']);
    queue.add('youtube:a', ['hola']);
    queue.add('youtube:b', []);
    expect(queue.take()).toEqual([{ media: 'youtube:a', tokens: ['hola', 'perro'] }]);
    expect(queue.take()).toEqual([]);
  });
});
