import { describe, expect, it } from 'vitest';
import { PlayedSeconds, watchVideoId } from './watchSignal';

describe('PlayedSeconds', () => {
  it('counts each second played once', () => {
    const played = new PlayedSeconds();
    for (let t = 0; t < 60; t++) played.add(t, t + 1);
    for (let t = 0; t < 30; t++) played.add(t, t + 1); // watched again
    expect(played.share(100)).toBe(0.6);
  });

  it('counts nothing across a seek or backwards', () => {
    const played = new PlayedSeconds();
    played.add(10, 70); // skipped ahead
    played.add(70, 69);
    expect(played.share(100)).toBe(0);
    played.add(70, 72); // 2x playback
    expect(played.share(100)).toBe(0.02);
  });

  it('survives a reload through its JSON', () => {
    const played = new PlayedSeconds();
    played.add(0, 2);
    expect(new PlayedSeconds(JSON.parse(JSON.stringify(played))).share(4)).toBe(0.5);
  });
});

describe('watchVideoId', () => {
  it('reads watch pages only', () => {
    expect(watchVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3')).toBe('dQw4w9WgXcQ');
    expect(watchVideoId('https://www.youtube.com/shorts/dQw4w9WgXcQ')).toBeNull();
    expect(watchVideoId('https://www.youtube.com/watch?v=bad')).toBeNull();
  });
});
