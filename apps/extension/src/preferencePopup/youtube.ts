// The popup's YouTube rows: Unmark for the video playing in this tab,
// yesterday's recap, and the history consent (docs/plans/youtube-plan.md,
// feature 2). Drawn for the active language; index.ts calls drawYoutube.

import { requestBackend } from '../api-service';
import { getLanguageInfo, type Language } from '../languages';
import { sendToBackground, type WatchState } from '../messages';
import { HISTORY_CONSENT_KEY, HISTORY_DECLINED_KEY, HISTORY_NEW_ACCOUNT_KEY, consentText, historyState } from '../watchHistory';
import { addLabel, picks, recapPath, recapStats, type Recap } from '../youtubeRecap';

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

function ask<T>(message: Parameters<typeof sendToBackground>[0]): Promise<T | undefined> {
  return new Promise((resolve) => sendToBackground<T>(message, (r) => resolve(chrome.runtime.lastError ? undefined : r)));
}

// --- This video ------------------------------------------------------------

function drawWatched(): void {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (tab?.id === undefined || !/^https:\/\/www\.youtube\.com\/watch/.test(tab.url ?? '')) return;
    const tabId = tab.id;
    chrome.tabs.sendMessage(tabId, { type: 'WATCH_STATE' }, (state: WatchState | null) => {
      if (chrome.runtime.lastError || !state?.videoId || !state.watched) return;
      const videoId = state.videoId;
      $('watchRow').classList.remove('hidden');
      const unmark = $<HTMLButtonElement>('unmarkBtn');
      unmark.onclick = async () => {
        unmark.disabled = true;
        const done = await ask<{ watched: boolean }>({ type: 'WATCH_UNMARK', videoId });
        if (!done) {
          unmark.disabled = false;
          return;
        }
        // The tab counts again from nothing, so a retry needs its own 70%.
        chrome.tabs.sendMessage(tabId, { type: 'WATCH_RESET' }, () => void chrome.runtime.lastError);
        $('watchText').textContent = 'Unmarked';
        unmark.classList.add('hidden');
        $('watchDot').classList.add('hidden');
      };
    });
  });
}

// --- Yesterday on YouTube --------------------------------------------------

let recapLanguage: Language | null = null;

async function drawRecap(language: Language): Promise<void> {
  recapLanguage = language;
  const box = $('recap');
  box.classList.add('hidden');
  const response = await requestBackend(recapPath(language));
  if (!response.ok || language !== recapLanguage) return;
  let recap: Recap;
  try {
    recap = JSON.parse(response.body) as Recap;
  } catch {
    return;
  }
  if (!recap.words.length) return;

  const left = new Set<number>();
  const add = $<HTMLButtonElement>('recapAdd');
  const words = $('recapWords');
  $('recapStats').textContent = recapStats(recap);
  words.replaceChildren();
  recap.words.forEach((w, i) => {
    if (i) words.append(', ');
    const word = document.createElement('button');
    word.type = 'button';
    word.className = 'recap-word';
    word.textContent = w.word;
    word.title = 'Leave out';
    word.onclick = () => {
      if (left.has(w.word_id)) left.delete(w.word_id);
      else left.add(w.word_id);
      word.classList.toggle('left', left.has(w.word_id));
      word.title = left.has(w.word_id) ? 'Keep' : 'Leave out';
      draw();
    };
    words.append(word);
  });
  const draw = () => {
    const count = recap.words.length - left.size;
    add.textContent = addLabel(count);
    add.disabled = count === 0;
  };
  draw();

  add.onclick = async () => {
    add.disabled = true;
    const done = await requestBackend('/api/watch/recap/add', { language, words: picks(recap, left) });
    if (!done.ok) {
      add.disabled = false;
      return;
    }
    $('recapActions').replaceChildren(Object.assign(document.createElement('p'), {
      className: 'recap-done', textContent: `Added ${recap.words.length - left.size} to reviews`,
    }));
  };
  $('recapClose').onclick = () => {
    box.classList.add('hidden');
    void requestBackend('/api/watch/recap/close', { day: recap.day });
  };
  box.classList.remove('hidden');
}

// --- History consent -------------------------------------------------------

async function drawHistory(language: Language): Promise<void> {
  const stored = await chrome.storage.local.get([HISTORY_CONSENT_KEY, HISTORY_DECLINED_KEY, HISTORY_NEW_ACCOUNT_KEY]);
  const state = historyState(stored);
  const prompt = $('historyAsk');
  const row = $('historyRow');
  prompt.classList.toggle('hidden', state !== 'ask');
  row.classList.toggle('hidden', state === 'ask');
  $('consentText').textContent = consentText(getLanguageInfo(language)?.name ?? 'learning-language');
  $('historyText').textContent = state === 'on' ? 'YouTube history is on' : 'YouTube history is off';
  const toggle = $<HTMLButtonElement>('historyToggle');
  toggle.textContent = state === 'on' ? 'Turn off' : 'Turn on';

  const allow = $<HTMLButtonElement>('historyAllow');
  const error = $('historyError');
  allow.onclick = async () => {
    allow.disabled = true;
    error.classList.add('hidden');
    const result = await ask<{ kept?: number; error?: string }>({ type: 'HISTORY_ALLOW' });
    allow.disabled = false;
    if (!result || result.error) {
      error.textContent = result?.error === 'Not signed in to YouTube'
        ? 'Sign in to YouTube in this browser first.'
        : 'Could not read the history page. Try again later.';
      error.classList.remove('hidden');
      return;
    }
    void drawHistory(language);
  };
  $('historyNo').onclick = async () => {
    await chrome.storage.local.set({ [HISTORY_DECLINED_KEY]: true, [HISTORY_NEW_ACCOUNT_KEY]: false });
    void drawHistory(language);
  };
  toggle.onclick = async () => {
    if (state === 'on') {
      toggle.disabled = true;
      await ask({ type: 'HISTORY_OFF' });
      toggle.disabled = false;
      void drawHistory(language);
    } else {
      prompt.classList.remove('hidden');
      row.classList.add('hidden');
    }
  };
}

export function drawYoutube(language: Language): void {
  drawWatched();
  void drawRecap(language);
  void drawHistory(language);
}
