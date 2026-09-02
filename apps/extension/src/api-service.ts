// Shared API helpers used by both reader.ts (extension page) and
// youtubeBookmark.ts (injected into the MAIN world of youtube.com pages).
// Plain ES exports instead of window.* globals, so each consumer's own
// Parcel bundle includes exactly what it imports rather than relying on a
// separate <script> tag having already run first.

import { BACKEND_URL, debugLog } from './config';

// Parse article content using backend
export async function parseArticleWithBackend(articleContent: string, language: string) {
  try {
    debugLog('Sending parse request to:', `${BACKEND_URL}/parse`);
    const response = await fetch(`${BACKEND_URL}/parse`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text: articleContent,
        language: language
      }),
    });

    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    console.error('Error parsing article:', error);
    return null;
  }
}

// Get translation for word
export async function fetchTranslation(word: string, language: string) {
  try {
    debugLog('Sending translation request for:', word);
    const response = await fetch(`${BACKEND_URL}/api/translate-word`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ word, language }),
    });

    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }

    const data = await response.json();
    return {
      id: parseInt(data.id),
      root: data.root,
      translation: data.translation,
    };
  } catch (error) {
    console.error('Translation error:', error);
    return null;
  }
}

// Save word to user's flashcards
export function saveWordToFlashcards(wordId: number) {
  window.postMessage({
    source: 'translationPopup',
    payload: { wordId }
  }, '*');
}

// Get translation for section
export async function translateSection(
  section: string,
  language: string,
): Promise<string | null> {
  try {
    debugLog('Sending section translation request');
    const response = await fetch(`${BACKEND_URL}/api/translate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ section, language }),
    });

    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }

    const rawText = await response.text();

    try {
      const data: unknown = JSON.parse(rawText);
      if (typeof data === 'string' && data.trim()) {
        return data;
      }
      if (typeof data === 'object' && data !== null) {
        if (
          'translation' in data &&
          typeof data.translation === 'string' &&
          data.translation.trim()
        ) {
          return data.translation;
        }

        const firstString = Object.values(data).find(
          (value): value is string =>
            typeof value === 'string' && value.trim().length > 0,
        );
        return firstString ?? null;
      }
    } catch {
      if (rawText.trim() && !rawText.includes('<!DOCTYPE html>')) {
        return rawText;
      }
    }

    return null;
  } catch (error) {
    console.error('Translation error:', error);
    return null;
  }
}

// Bookmark YouTube channel for indexing
export async function bookmarkChannel(channelId: string) {
  try {
    const response = await fetch(`${BACKEND_URL}/youtube/bookmarks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: channelId })
    });
    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }
    return await response.json();
  } catch (error) {
    console.error('Bookmark channel error:', error);
    return null;
  }
}

// Check if a YouTube channel was already indexed
export async function checkChannelBookmarked(channelId: string) {
  try {
    const response = await fetch(`${BACKEND_URL}/youtube/bookmarks/${encodeURIComponent(channelId)}`);
    if (!response.ok) return { saved: false };
    return await response.json();
  } catch (error) {
    console.error('Check channel bookmarked error:', error);
    return { saved: false };
  }
}
