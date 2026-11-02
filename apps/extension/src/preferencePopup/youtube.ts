// The popup's YouTube rows: Unmark for the video playing in this tab,
// yesterday's recap, and turning the history read off or on
// (docs/plans/youtube-plan.md, feature 2). Drawn for the active language;
// index.ts calls drawYoutube.

import { requestBackend } from '../api-service';
import type { Language } from '../languages';
import { sendToBackground, type WatchState } from '../messages';
import { HISTORY_CONSENT_KEY, HISTORY_DECLINED_KEY, HISTORY_NEW_ACCOUNT_KEY, historyState } from '../watchHistory';
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
    let added: string[];
    try {
      if (!done.ok) throw new Error(done.statusText);
      added = (JSON.parse(done.body) as { added: string[] }).added;
    } catch {
      add.disabled = false;
      return;
    }
    // The API's count: a word saved meanwhile elsewhere isn't added again.
    $('recapActions').replaceChildren(Object.assign(document.createElement('p'), {
      className: 'recap-done', textContent: `Added ${added.length} to reviews`,
    }));
  };
  $('recapClose').onclick = () => {
    box.classList.add('hidden');
    void requestBackend('/api/watch/recap/close', { day: recap.day });
  };
  box.classList.remove('hidden');
}

// --- History -----------------------------------------------------------------

// The consent itself is a card in the corner of youtube.com
// (historyPrompt.ts). Here, once answered, one line to turn it off or on.
async function drawHistory(): Promise<void> {
  const stored = await chrome.storage.local.get([HISTORY_CONSENT_KEY, HISTORY_DECLINED_KEY, HISTORY_NEW_ACCOUNT_KEY]);
  const state = historyState(stored);
  const row = $('historyRow');
  row.classList.toggle('hidden', state === 'ask');
  $('historyText').textContent = state === 'on' ? 'YouTube history is on' : 'YouTube history is off';
  const toggle = $<HTMLButtonElement>('historyToggle');
  toggle.textContent = state === 'on' ? 'Turn off' : 'Turn on';
  toggle.onclick = async () => {
    toggle.disabled = true;
    if (state === 'on') {
      await ask({ type: 'HISTORY_OFF' });
      toggle.disabled = false;
      void drawHistory();
      return;
    }
    // Asking again: the card shows on the YouTube tab, or on a new one.
    await chrome.storage.local.set({ [HISTORY_DECLINED_KEY]: false });
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!/^https:\/\/www\.youtube\.com\//.test(tabs[0]?.url ?? '')) chrome.tabs.create({ url: 'https://www.youtube.com/' });
      window.close();
    });
  };
}

export function drawYoutube(language: Language): void {
  drawWatched();
  void drawRecap(language);
  void drawHistory();
}
