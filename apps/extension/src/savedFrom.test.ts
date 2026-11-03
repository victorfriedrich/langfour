import { describe, expect, it } from 'vitest';
import { savedContext } from './savedFrom';

describe('savedContext', () => {
  it('names the video of a YouTube watch page', () => {
    expect(savedContext('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s')).toEqual({
      site: 'youtube',
      media: 'youtube:dQw4w9WgXcQ',
    });
    expect(savedContext('https://m.youtube.com/watch?v=dQw4w9WgXcQ')?.media).toBe('youtube:dQw4w9WgXcQ');
  });

  it('names nothing anywhere else', () => {
    for (const url of [
      undefined,
      'not a url',
      'https://www.youtube.com/',
      'https://www.youtube.com/shorts/dQw4w9WgXcQ',
      'https://www.youtube.com/watch?v=short',
      'https://example.com/watch?v=dQw4w9WgXcQ',
      'http://www.youtube.com/watch?v=dQw4w9WgXcQ',
    ]) {
      expect(savedContext(url)).toBeNull();
    }
  });
});
