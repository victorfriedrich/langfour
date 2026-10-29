// reader.ts

import { getPrefs, Prefs, setPrefs } from './preferencePopup/prefs';
import { Language, LANGUAGES, toLanguage } from './languages';
import { fetchTranslation, requestBackend, translateSection } from './api-service';
import { Block, buildLibraryImport, existingIdFrom, Passage } from './libraryImport';
import { sanitizeHTML } from './sanitizeHTML';
import { WEB_URL } from './config';
import { AccountResponse, askBackground, ClassifyWordsResponse, sendToBackground, WordProgressResponse, WordStatus } from './messages';
import { loadArticle, StoredArticle } from './readerArticles';
import { hostOf } from './pageTitle';
import { appendWordProgress, createLoadingPopup, createMessagePopup, createWordPopup } from './wordPopup';

let readerLanguage: Language | null = null;
let signedIn = false;
// Where "Review flashcards" goes: RemNote for users who review there.
let reviewUrl = `${WEB_URL}/vocabulary`;

/**
 * Phones get bottom sheets instead of popups anchored to the word: a
 * 280px popup under a word near the screen edge gets clipped or covers the
 * line being read, and the sheet keeps its buttons under the thumb.
 */
const sheetQuery = window.matchMedia('(max-width: 600px), (pointer: coarse)');
const useSheets = () => sheetQuery.matches;

const WORDS_PER_MINUTE = 200;

document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('reader-container') as HTMLElement | null;

  if (!container) {
    console.error('Reader container not found.');
    return;
  }

  // --- Load Article Content from Storage ---
  // Show a spinner while loading
  const spinnerElement = document.createElement('div');
  spinnerElement.className = 'spinner';
  spinnerElement.style.margin = '50px auto';
  container.appendChild(spinnerElement);

  const articleId = new URLSearchParams(window.location.search).get('id');
  Promise.all([loadArticle(articleId), chrome.storage.local.get('supabaseSession')])
    .then(([article, { supabaseSession }]) => {
      spinnerElement.remove();
      signedIn = Boolean(supabaseSession?.access_token);
      initBackToPage(article);
      void initAccount();

      if (!article || article.error) {
        renderProblem(container, article);
        return;
      }
      renderArticle(container, article);
    })
    .catch((error: unknown) => {
      console.error('Could not load the article:', error);
      spinnerElement.remove();
      renderProblem(container, null);
    });

  // Signing in or out while the reader is open: reload so words get
  // highlighted and become translatable without the user doing anything.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes.supabaseSession) return;
    const nowSignedIn = Boolean(changes.supabaseSession.newValue?.access_token);
    if (nowSignedIn !== signedIn) window.location.reload();
  });

  // --- Attach event handlers ---
  container.addEventListener('click', (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    // In the article a tap means "translate". Most Wikipedia words are
    // links, and following one would leave the reader; a long press still
    // gives the system link preview.
    if (target.closest('.article-content a')) e.preventDefault();
    if (!target.classList?.contains('word')) return;

    // If it’s already active, close and bail out
    if (target.classList.contains('word-active')) {
      closeWordPopups();
      return;
    }

    // Otherwise show a new popup
    handleWordClick(target);

    // Don’t let this bubble up and trigger the document listener below
    e.stopPropagation();
  });

  // A double click on a new word saves it without the popup.
  container.addEventListener('dblclick', (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (!target.classList?.contains('word')) return;
    closeWordPopups();
    if (!signedIn || !readerLanguage || !isNewWord(target)) return;
    window.getSelection()?.removeAllRanges();
    quickSave(target, readerLanguage);
  });

  // Escape dismisses any open word popup.
  document.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Escape') closeWordPopups();
  });

  // Handle clicks anywhere else to dismiss the popup
  document.addEventListener('click', (e: MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest('.word-popup') || target.classList?.contains('word')) {
      return;
    }
    closeWordPopups();
  });

  // --- Initialize Top Bar, Settings Panel, and Scroll Progress ---
  initTopbar();
  initSettingsPanel();
  initSwipeToDismiss();
  window.addEventListener('scroll', updateScrollProgress, { passive: true });
  initToolbarAutoHide();
  updateScrollProgress(); // Set initial progress
});


// ====================== Article Rendering ======================

function renderArticle(container: HTMLElement, article: StoredArticle): void {
  const sanitizedArticle = sanitizeHTML(article.content || '');
  container.innerHTML = '';
  document.title = article.title ? `${article.title} · Langfour Reader` : 'Langfour Reader';

  const contentDiv = document.createElement('div');
  contentDiv.className = 'article-content';
  // Cleaned when it was extracted (articleExtraction.ts); sanitized again
  // here because it comes out of storage.
  contentDiv.innerHTML = sanitizedArticle;

  // Header: where the text is from, the title (unless the content already
  // starts with one), and a meta line filled in once words are counted.
  const header = document.createElement('header');
  header.className = 'article-header';
  const source = article.siteName || hostOf(article.url);
  if (source) {
    const sourceEl = document.createElement(article.url ? 'a' : 'span');
    sourceEl.className = 'article-source';
    sourceEl.textContent = source;
    if (sourceEl instanceof HTMLAnchorElement && article.url) sourceEl.href = article.url;
    header.appendChild(sourceEl);
  }
  if (article.title) {
    document.title = `${article.title} · Langfour Reader`;
    const titleElement = document.createElement('h1');
    titleElement.textContent = article.title;
    titleElement.className = 'article-title';
    header.appendChild(titleElement);
  }
  const meta = document.createElement('p');
  meta.className = 'article-meta';
  header.appendChild(meta);
  container.append(header, contentDiv);

  const wordCount = (contentDiv.textContent || '').split(/\s+/).filter(Boolean).length;
  const metaParts: string[] = [];
  if (article.byline) metaParts.push(article.byline);
  metaParts.push(`${Math.max(1, Math.round(wordCount / WORDS_PER_MINUTE))} min read`);
  const setMeta = (extra?: string) => {
    meta.textContent = [...metaParts, ...(extra ? [extra] : [])].join(' · ');
  };
  setMeta();

  if (!signedIn) {
    // Without a session there is no known-words list (every word would be
    // highlighted) and no translations, so show the text plainly and say
    // how to unlock the rest.
    wrapWords(contentDiv);
    document.getElementById('toggle-highlight')?.setAttribute('hidden', '');
    const signIn = document.createElement('button');
    signIn.type = 'button';
    signIn.className = 'signin-cta';
    signIn.textContent = 'Sign in to translate';
    signIn.addEventListener('click', openSignIn);
    header.appendChild(signIn);
    return;
  }

  wrapWords(contentDiv);

  getPrefs((prefs) => {
    readerLanguage = toLanguage(prefs.preferredLanguage);
    if (!readerLanguage) {
      console.warn('Reader: unrecognised preferred language', prefs.preferredLanguage);
      return;
    }
    setupSectionTranslation(readerLanguage);
    header.appendChild(createLibraryButton(article, contentDiv, readerLanguage));

    // The text shows right away; marks follow once the dictionary has said
    // which tokens are words and where the user stands with them.
    setMeta('checking words…');
    void classifyArticleWords(contentDiv, readerLanguage).then((newWords) => {
      if (newWords === null) {
        setMeta();
      } else {
        setMeta(newWords > 0 ? `${newWords} new ${newWords === 1 ? 'word' : 'words'}` : 'no new words');
      }
    });
  });
}

const BLOCKS = 'p, li, h2, h3, h4, h5, blockquote, pre, figcaption';

// h5 is rare enough to share h4's look.
const BLOCK_OF: Record<string, Block> = { H2: 'h2', H3: 'h3', H4: 'h4', H5: 'h4', LI: 'li', BLOCKQUOTE: 'blockquote', PRE: 'pre', FIGCAPTION: 'figcaption' };

/** The reader's text, one passage per paragraph, heading, list item or stanza. */
function passagesOf(root: HTMLElement): Passage[] {
  const blocks = Array.from(root.querySelectorAll<HTMLElement>(BLOCKS)).filter((el) => !el.querySelector(BLOCKS));
  // innerText keeps the <br>s between lyric lines, which textContent drops.
  return blocks.length ? blocks.map((el) => ({ text: el.innerText, block: BLOCK_OF[el.tagName] })) : [{ text: root.innerText }];
}

/**
 * "Add to Library": sends the page to the web app's Library, where its words
 * can be learned as a list before (or instead of) reading it here.
 */
function createLibraryButton(article: StoredArticle, contentDiv: HTMLElement, language: Language): HTMLElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'library-btn';
  const idle = () => { button.disabled = false; button.textContent = 'Add to Library'; };
  const done = (id: string, label: string) => {
    const link = document.createElement('a');
    link.className = 'library-btn library-done';
    link.href = `${WEB_URL}/media/${encodeURIComponent(id)}`;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = label;
    button.replaceWith(link);
  };
  idle();
  button.addEventListener('click', async () => {
    const payload = buildLibraryImport(article, passagesOf(contentDiv), language);
    if (!payload) return showToast('There is no text to add.');
    button.disabled = true;
    button.textContent = 'Adding…';
    const response = await requestBackend('/api/media/import', payload);
    if (response.ok) {
      try {
        return done(JSON.parse(response.body).id, 'Open in Library');
      } catch { /* fall through to the error */ }
    }
    const existing = response.status === 409 ? existingIdFrom(response.body) : null;
    if (existing) return done(existing, 'Already in Library');
    console.error('Add to Library failed:', response.status, response.statusText, response.body);
    showToast(response.status === 401 ? 'Sign in again to add this.' : 'Could not add this to your Library.');
    idle();
  });
  return button;
}

const WORD_STATUS_CLASS: Partial<Record<WordStatus, string>> = {
  new: 'unknown-word',
  learning: 'learning-word',
};

/**
 * Marks every wrapped word with what classify_words says about it: new
 * words get the highlight, words being learned a quieter mark, and known
 * words, names and anything else that is not vocabulary stay plain. Each
 * span also gets its word id, so saving a word can mark all its forms.
 * Returns the number of distinct new words, or null if classification
 * failed (the text then stays unmarked rather than wrongly marked).
 */
async function classifyArticleWords(root: HTMLElement, language: Language): Promise<number | null> {
  const spans = Array.from(root.querySelectorAll<HTMLElement>('span.word'));
  const tokens = Array.from(new Set(spans.map((span) => span.textContent || '')));
  // Safari can drop the background's reply, so a request without an answer
  // is sent again. That is cheap now: words are matched in the background
  // without a request, and a retry during the first dictionary download
  // (which can take longer than the default 10 s) joins that download.
  const response = await askBackground<ClassifyWordsResponse>(
    { type: 'CLASSIFY_WORDS', language, tokens },
    { timeoutMs: 20_000 },
  );
  if (!response?.ok) {
    console.warn('Could not classify words:', response ? response.error : 'no response');
    return null;
  }

  const byToken = new Map(response.words.map((word) => [word.token, word]));
  const newWordIds = new Set<number>();
  for (const span of spans) {
    const word = byToken.get(span.textContent || '');
    if (!word) continue;
    span.dataset.wordId = String(word.word_id);
    span.dataset.wordStatus = word.status;
    const cls = WORD_STATUS_CLASS[word.status];
    if (cls) span.classList.add(cls);
    if (word.status === 'new') newWordIds.add(word.word_id);
  }
  return newWordIds.size;
}

function renderProblem(container: HTMLElement, article: StoredArticle | null): void {
  container.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'reader-problem';
  const title = document.createElement('h1');
  title.textContent = article?.title || 'Nothing to read yet';
  const text = document.createElement('p');
  text.textContent = article?.content
    || 'Open an article in Safari, then choose Langfour in the page menu.';
  box.append(title, text);
  if (article?.url) {
    const back = document.createElement('button');
    back.type = 'button';
    back.className = 'problem-btn';
    back.textContent = 'Back to the page';
    back.addEventListener('click', () => leaveReader(article.url));
    box.appendChild(back);
  }
  container.appendChild(box);
}

/**
 * Opened from the popup, the reader replaced the original page in the same
 * tab, so Back returns to it with its scroll position. Opened in a new tab
 * (keyboard command) there is nothing to go back to, so load the page.
 */
function leaveReader(url: string | null | undefined): void {
  if (window.history.length > 1) {
    window.history.back();
  } else if (url) {
    window.location.assign(url);
  }
}

function initBackToPage(article: StoredArticle | null): void {
  const btn = document.getElementById('back-to-page');
  if (!btn) return;
  if (!article?.url && window.history.length <= 1) {
    btn.style.visibility = 'hidden';
    return;
  }
  // "‹ es.wikipedia.org" says where Back goes, like Safari's own back label.
  const label = document.getElementById('back-label');
  const site = article?.siteName || hostOf(article?.url);
  if (label && site) label.textContent = site;
  btn.addEventListener('click', () => leaveReader(article?.url));
}


// ====================== Text Processing Functions ======================

// Letters and combining marks make words; everything else (spaces of any
// kind, line breaks, digits, punctuation, dashes, quotes) separates them.
const WORD_CHAR = /[\p{L}\p{M}]/u;

type TextGroup = { content: string; isWord: boolean };

// Split text into groups of word and non-word characters.
function groupText(text: string): TextGroup[] {
  if (!text) return [];
  const result: TextGroup[] = [];
  let currentGroup = '';
  let currentIsSpecial: boolean | null = null;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const isSpecial = !WORD_CHAR.test(char);
    if (currentGroup === '') {
      currentGroup = char;
      currentIsSpecial = isSpecial;
    } else if (isSpecial === currentIsSpecial) {
      currentGroup += char;
    } else {
      result.push({ content: currentGroup, isWord: !currentIsSpecial });
      currentGroup = char;
      currentIsSpecial = isSpecial;
    }
  }

  if (currentGroup !== '') {
    result.push({ content: currentGroup, isWord: !currentIsSpecial });
  }

  return result;
}

// Wrap every word of the text in a span, so it can be tapped and marked.
function wrapWords(container: HTMLElement): void {
  if (!container) return;
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
  const nodesToProcess: Node[] = [];
  let node: Node | null;
  while ((node = walker.nextNode())) {
    if (node.nodeValue?.trim().length) {
      nodesToProcess.push(node);
    }
  }

  nodesToProcess.forEach(node => {
    const groups = groupText(node.nodeValue || '');
    const frag = document.createDocumentFragment();
    groups.forEach(group => {
      if (group.isWord) {
        const span = document.createElement('span');
        span.className = 'word';
        if (group.content.trim().length > 0) {
          span.textContent = group.content;
          frag.appendChild(span);
        }
      } else {
        frag.appendChild(document.createTextNode(group.content));
      }
    });
    if (node.parentNode) {
      node.parentNode.replaceChild(frag, node);
    }
  });
}


// ====================== Word Popup and Translation ======================

// Handle click on a word to show its translation popup.
function handleWordClick(wordElement: HTMLElement): void {
  closeWordPopups();
  if (!wordElement) return;

  wordElement.classList.add('word-active');

  if (!signedIn || !readerLanguage) {
    const popup = createMessagePopup(
      wordElement.textContent || '',
      signedIn
        ? 'Pick the language you are learning in the reader’s Aa settings first.'
        : 'Sign in to see translations and save words.',
    );
    if (!signedIn) {
      const signInBtn = document.createElement('button');
      signInBtn.className = 'flashcard-btn';
      signInBtn.textContent = 'Sign in';
      signInBtn.addEventListener('click', openSignIn);
      popup.appendChild(signInBtn);
    }
    showPopup(popup, wordElement);
    return;
  }
  const language = readerLanguage;

  // Create and show a loading popup for translation.
  const loadingPopup = createLoadingPopup(wordElement.textContent || '');
  showPopup(loadingPopup, wordElement);

  fetchTranslation(wordElement.textContent || '', language).then((translation) => {
    // The user may have tapped another word meanwhile.
    if (!loadingPopup.isConnected) return;
    loadingPopup.remove();

    if (!translation) {
      const failed = createMessagePopup(wordElement.textContent || '', 'Could not load the translation.');
      const retryBtn = document.createElement('button');
      retryBtn.className = 'flashcard-btn';
      retryBtn.textContent = 'Try again';
      retryBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        handleWordClick(wordElement);
      });
      // Progress comes from Supabase, so it shows even when the
      // translation (from the API) does not.
      appendProgress(failed, wordElement);
      failed.appendChild(retryBtn);
      showPopup(failed, wordElement);
      return;
    }

    const wordText = wordElement.textContent || '';
    const popup = createWordPopup(
      wordText,
      translation,
      readerLanguage,
      translation.id && isNewWord(wordElement) ? createFlashcardButton(wordText, translation.id) : undefined,
    );
    appendProgress(popup, wordElement);
    showPopup(popup, wordElement);
  });
}

function showPopup(popup: HTMLElement, wordElement: HTMLElement): void {
  document.body.appendChild(popup);
  positionPopup(popup, wordElement);
  // Next frame, so the transition runs from the hidden state.
  requestAnimationFrame(() => popup.classList.add('show'));
}

/**
 * Only words classify_words reported as new can be saved. Saving one the user
 * already has resets it to learning (move_words_to_userwords re-inserts it),
 * so an unclassified word (check still running, or failed) is not offered.
 */
function isNewWord(wordElement: HTMLElement): boolean {
  return wordElement.dataset.wordStatus === 'new';
}

/** Words the user is learning or knows are already in their flashcards. */
function isInUserWords(wordElement: HTMLElement): boolean {
  const status = wordElement.dataset.wordStatus;
  return status === 'learning' || status === 'known';
}

/** For a word the user is learning or knows: how its reviews went. */
function appendProgress(popup: HTMLElement, wordElement: HTMLElement): void {
  const wordId = Number(wordElement.dataset.wordId);
  if (isInUserWords(wordElement) && wordId) appendWordProgress(popup, wordId);
}

/**
 * Saves through the background, which holds the Supabase session. The
 * reader used to call api-service's saveWordToFlashcards, which posts a
 * window message for the subtitle content script's relay; an extension page
 * has no such listener, so the button said "Added" while nothing was saved.
 */
function createFlashcardButton(wordText: string, wordId: number): HTMLButtonElement {
  const btn = document.createElement('button');
  btn.className = 'flashcard-btn';
  btn.textContent = 'Add to flashcards';
  btn.addEventListener('click', (e: MouseEvent) => {
    e.stopPropagation();
    // The marks switching to "learning" are the confirmation; the sheet has
    // nothing left to say. Only a failure is worth interrupting for.
    closeWordPopups();
    saveToFlashcards(wordText, wordId);
  });
  return btn;
}

function saveToFlashcards(wordText: string, wordId: number): void {
  const undo = markSaved(wordText, wordId);
  sendToBackground<{ success: boolean; error?: string }>(
    { type: 'ADD_WORD_TO_USERWORDS', wordId },
    (response) => {
      if (response?.success) return;
      if (response) {
        console.error('Could not save word:', response.error);
        saveFailed(wordText, undo);
        return;
      }
      // No answer at all: Safari can drop the reply of a save that went
      // through, so ask whether the word is now among the user's.
      void askBackground<WordProgressResponse>({ type: 'WORD_PROGRESS', wordId }).then((progress) => {
        // word_progress also returns a row for unsaved words (status
        // 'new'); only an active saved word confirms the write succeeded.
        if (progress?.ok && (progress.progress?.status === 'learning' || progress.progress?.status === 'known')) return;
        console.error('Could not save word: no answer from the background');
        saveFailed(wordText, undo);
      });
    },
  );
}

/**
 * The double-click save. The marks turn "learning" at once; the save waits
 * for the translation, whose id is the base form the button would save.
 */
function quickSave(wordElement: HTMLElement, language: string): void {
  const wordText = wordElement.textContent || '';
  const undo = markSaved(wordText, Number(wordElement.dataset.wordId) || 0);
  void fetchTranslation(wordText, language).then((translation) => {
    undo();
    if (translation?.id) saveToFlashcards(wordText, translation.id);
    else saveFailed(wordText, () => undefined);
  });
}

function saveFailed(wordText: string, undo: () => void): void {
  undo();
  showToast(`Couldn’t save “${wordText}”. Please try again.`);
}

/** A short notice above the toolbar, for the rare thing worth interrupting for. */
function showToast(message: string): void {
  document.querySelector('.reader-toast')?.remove();
  const toast = document.createElement('div');
  toast.className = 'reader-toast';
  toast.setAttribute('role', 'alert');
  toast.textContent = message;
  document.body.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

/**
 * A saved word is now being learned: every form of it in the article (same
 * word id from classify_words) and every occurrence of the tapped spelling
 * switch to the learning mark. Returns a function that puts the marks back.
 */
function markSaved(wordText: string, wordId: number): () => void {
  const needle = wordText.toLowerCase();
  const changed: { span: HTMLElement; className: string; status?: string; id?: string }[] = [];
  document.querySelectorAll<HTMLElement>('.article-content span.word').forEach((span) => {
    if (span.dataset.wordId === String(wordId) || (span.textContent || '').toLowerCase() === needle) {
      changed.push({ span, className: span.className, status: span.dataset.wordStatus, id: span.dataset.wordId });
      span.classList.remove('unknown-word');
      span.classList.add('learning-word');
      span.dataset.wordStatus = 'learning';
      span.dataset.wordId ||= String(wordId);
    }
  });
  return () => {
    for (const { span, className, status, id } of changed) {
      span.className = className;
      if (status === undefined) delete span.dataset.wordStatus;
      else span.dataset.wordStatus = status;
      if (id === undefined) delete span.dataset.wordId;
      else span.dataset.wordId = id;
    }
  };
}

// Position a popup relative to a reference element.
function positionPopup(popup: HTMLElement, referenceElement: HTMLElement): void {
  if (!popup || !referenceElement) return;
  if (useSheets()) {
    popup.classList.add('sheet');
    // Keep the tapped word visible above the sheet.
    const rect = referenceElement.getBoundingClientRect();
    const sheetTop = window.innerHeight - popup.getBoundingClientRect().height;
    if (rect.bottom > sheetTop - 16) {
      window.scrollBy({ top: rect.bottom - sheetTop + 48, behavior: 'smooth' });
    }
    return;
  }
  const rect = referenceElement.getBoundingClientRect();
  const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
  popup.style.top = `${rect.bottom + scrollTop + 10}px`;
  popup.style.left = `${rect.left}px`;

  const viewportWidth = window.innerWidth;
  const popupRect = popup.getBoundingClientRect();
  if (popupRect.right > viewportWidth - 20) {
    popup.style.left = `${viewportWidth - popupRect.width - 20}px`;
  }
}

// Remove all word popups and clear active word highlights.
function closeWordPopups(): void {
  document.querySelectorAll('.word-popup').forEach(popup => {
    popup.classList.remove('show');
    setTimeout(() => popup.parentNode?.removeChild(popup), 300);
  });
  document.querySelectorAll('.word-active').forEach(word => {
    word.classList.remove('word-active');
  });
}


// ====================== Section Translation (on Text Selection) ======================

type PopupPosition = { top: string; left: string; transform: string };
type PopupInfo = { text: string; position: PopupPosition | null; translation?: string };

// How long a touch selection has to stay put before it is translated, so
// dragging the selection handles does not fire a request per step.
const TOUCH_SELECTION_DELAY_MS = 700;

function setupSectionTranslation(language: Language): void {
  let currentPopupInfo: PopupInfo | null = null;
  let justSelected = false;
  let lastTranslated = '';

  function selectedPhrase(): string | null {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return null;
    const text = selection.toString().trim();
    if (!text || text.split(/\s+/).length < 2) return null;
    // Only text inside the article, not the toolbar or a sheet.
    const anchor = selection.anchorNode?.parentElement;
    if (!anchor?.closest('.article-content')) return null;
    return text;
  }

  function translateSelection(text: string) {
    let position: PopupPosition | null = null;
    const selection = window.getSelection();
    if (!useSheets() && selection && selection.rangeCount > 0) {
      const range = selection.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
      const popupWidth = 400;
      let leftPos = rect.left + (rect.width / 2) - (popupWidth / 2);
      const viewportWidth = window.innerWidth;
      if (leftPos < 20) leftPos = 20;
      if (leftPos + popupWidth > viewportWidth - 20) leftPos = viewportWidth - popupWidth - 20;
      position = { top: `${rect.bottom + scrollTop + 10}px`, left: `${leftPos}px`, transform: 'none' };
    }

    lastTranslated = text;
    currentPopupInfo = { text, position };
    closeWordPopups();
    showTranslationLoadingPopup();
    translateSection(text, language).then((translation) => {
      // A newer selection replaced this one meanwhile.
      if (currentPopupInfo?.text !== text) return;
      showTranslationPopup(translation || 'No translation available');
    });
  }

  function handleTextSelection(event: MouseEvent) {
    if ((event.target as HTMLElement).closest('.dismissable-popup, .word-popup')) return;
    const text = selectedPhrase();
    if (!text) return;
    justSelected = true;
    translateSelection(text);
  }

  // Touch selection never ends in a mouseup, so watch the selection itself.
  let selectionTimer: number | undefined;
  function handleSelectionChange() {
    if (!sheetQuery.matches) return;
    window.clearTimeout(selectionTimer);
    selectionTimer = window.setTimeout(() => {
      const text = selectedPhrase();
      if (text && text !== lastTranslated) translateSelection(text);
      if (!text) lastTranslated = '';
    }, TOUCH_SELECTION_DELAY_MS);
  }

  function handleDocumentClick(event: MouseEvent) {
    if (justSelected) { justSelected = false; return; }
    if (!(event.target as HTMLElement).closest('.dismissable-popup, .word-popup')) {
      removeTranslationPopups();
      currentPopupInfo = null;
      lastTranslated = '';
    }
  }

  function removeTranslationPopups() {
    document.querySelectorAll('.dismissable-popup').forEach(popup => {
      popup.classList.remove('show');
      setTimeout(() => popup.remove(), 300);
    });
  }

  function placePopup(popup: HTMLElement) {
    if (currentPopupInfo?.position) {
      Object.assign(popup.style, currentPopupInfo.position);
    } else {
      popup.classList.add('sheet');
    }
  }

  function showTranslationLoadingPopup() {
    removeTranslationPopups();
    const popup = document.createElement('div');
    popup.className = 'dismissable-popup';
    popup.id = 'dismissable-popup-' + Date.now();
    placePopup(popup);
    popup.innerHTML = `
      <div class="sheet-handle" aria-hidden="true"></div>
      <div class="dismissable-original"></div>
      <div class="dismissable-loading">
        <div class="dismissable-spinner"></div>
        <div>Translating...</div>
      </div>
    `;
    const original = popup.querySelector('.dismissable-original');
    if (original) original.textContent = currentPopupInfo?.text || '';
    document.body.appendChild(popup);
    requestAnimationFrame(() => popup.classList.add('show'));
  }

  function showTranslationPopup(translation: string) {
    const popupId = 'dismissable-popup-' + Date.now();
    const popup = document.createElement('div');
    popup.className = 'dismissable-popup';
    popup.id = popupId;
    placePopup(popup);
    const handle = document.createElement('div');
    handle.className = 'sheet-handle';
    handle.setAttribute('aria-hidden', 'true');
    const original = document.createElement('div');
    original.className = 'dismissable-original';
    original.textContent = currentPopupInfo?.text || '';
    const translated = document.createElement('div');
    translated.className = 'dismissable-translation';
    translated.textContent = translation || 'No translation available';
    popup.append(handle, original, translated);
    document.body.appendChild(popup);
    if (currentPopupInfo) currentPopupInfo.translation = translation;
    // The new popup arrives already visible, so the swap does not flash.
    popup.classList.add('show', 'no-transition');
    document.querySelectorAll('.dismissable-popup').forEach(existingPopup => {
      if (existingPopup.id !== popupId) existingPopup.remove();
    });
  }

  document.addEventListener('mouseup', handleTextSelection);
  document.addEventListener('click', handleDocumentClick);
  document.addEventListener('selectionchange', handleSelectionChange);
}


// ====================== Swipe Down to Dismiss Sheets ======================

const DISMISS_DISTANCE_PX = 70;

/**
 * Sheets have a grab handle, so they should follow a finger down and close
 * when let go far enough, like system sheets. Only from the top of the
 * sheet's own scroll, so scrolling a long translation still works.
 */
function initSwipeToDismiss(): void {
  let sheet: HTMLElement | null = null;
  let startY = 0;
  let dy = 0;

  document.addEventListener('touchstart', (e) => {
    const target = (e.target as HTMLElement).closest<HTMLElement>('.sheet.show, .settings-panel.show');
    if (!target || !sheetQuery.matches || target.scrollTop > 0) return;
    sheet = target;
    startY = e.touches[0].clientY;
    dy = 0;
  }, { passive: true });

  document.addEventListener('touchmove', (e) => {
    if (!sheet) return;
    dy = Math.max(0, e.touches[0].clientY - startY);
    sheet.style.transition = 'none';
    sheet.style.transform = `translateY(${dy}px)`;
  }, { passive: true });

  document.addEventListener('touchend', () => {
    if (!sheet) return;
    const el = sheet;
    sheet = null;
    // Clearing the inline styles hands the position back to the stylesheet,
    // which animates from where the finger left it.
    el.style.transition = '';
    if (dy < DISMISS_DISTANCE_PX) {
      el.style.transform = '';
      return;
    }
    if (el.classList.contains('word-popup')) {
      closeWordPopups();
    } else if (el.classList.contains('settings-panel')) {
      el.classList.remove('show');
      document.getElementById('reader-settings')?.setAttribute('aria-expanded', 'false');
    } else {
      el.classList.remove('show');
      window.getSelection()?.removeAllRanges();
      setTimeout(() => el.remove(), 300);
    }
    el.style.transform = '';
  });
}


// ====================== Scroll Progress Indicator ======================

function updateScrollProgress(): void {
  const scrollTop = window.scrollY;
  const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
  const scrollPercentage = scrollHeight > 0 ? (scrollTop / scrollHeight) * 100 : 0;
  (document.getElementById('scroll-progress-bar') as HTMLElement).style.width = scrollPercentage + '%';
}


/**
 * Like Safari's own bars, the top bar gets out of the way while reading
 * down and comes back as soon as the reader scrolls up.
 */
function initToolbarAutoHide(): void {
  const toolbar = document.getElementById('topbar');
  if (!toolbar) return;
  let lastY = window.scrollY;
  window.addEventListener('scroll', () => {
    const y = window.scrollY;
    if (Math.abs(y - lastY) < 8) return;
    const settingsOpen = document.getElementById('settings-panel')?.classList.contains('show');
    toolbar.classList.toggle('toolbar-hidden', y > lastY && y > 80 && !settingsOpen);
    lastY = y;
  }, { passive: true });
}


// ====================== Sidebar and Settings Panel ======================

function initTopbar(): void {
  const highlightBtn = document.getElementById('toggle-highlight') as HTMLElement;
  const flashcardsBtn = document.getElementById('access-flashcards') as HTMLElement;
  const settingsBtn = document.getElementById('reader-settings') as HTMLElement;
  const settingsPanel = document.getElementById('settings-panel') as HTMLElement;

  // Highlighting of new words; the class on <body> also covers words wrapped
  // after the toggle (known words load asynchronously).
  highlightBtn.addEventListener('click', () => {
    const off = document.body.classList.toggle('highlight-off');
    highlightBtn.setAttribute('aria-pressed', String(!off));
  });

  flashcardsBtn.addEventListener('click', () => {
    window.open(reviewUrl, '_blank', 'noopener');
  });
  document.getElementById('sign-in')?.addEventListener('click', openSignIn);
  document.getElementById('sign-out')?.addEventListener('click', () => void signOut());

  settingsBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    closeWordPopups();
    const open = settingsPanel.classList.toggle('show');
    settingsBtn.setAttribute('aria-expanded', String(open));
  });
}

// ====================== Account ======================

/** The sign-in page; the reader reloads by itself once a session appears. */
function openSignIn(): void {
  void chrome.tabs.create({ url: chrome.runtime.getURL('src/auth.html') });
}

/**
 * The settings panel's account section: the language being learned, the
 * review and app links, and signing out. Signed out, only "Sign in".
 */
async function initAccount(): Promise<void> {
  const section = document.getElementById('settings-account') as HTMLElement;
  const signIn = document.getElementById('sign-in') as HTMLElement;
  if (!signedIn) {
    signIn.hidden = false;
    return;
  }
  const response = await askBackground<AccountResponse>({ type: 'GET_ACCOUNT' });
  const account = response?.account;
  if (!account) {
    // The stored session no longer works; offer a fresh sign-in.
    if (response) signIn.hidden = false;
    return;
  }

  (document.getElementById('account-email') as HTMLElement).textContent = account.email;
  (document.getElementById('review-label') as HTMLElement).textContent = account.review.label;
  reviewUrl = account.review.url;

  const select = document.getElementById('account-languages') as HTMLSelectElement;
  // The language the reader actually uses (local prefs), which can differ
  // from the account's default; readerLanguage may not be set yet.
  const prefs = await new Promise<Prefs>((resolve) => getPrefs(resolve));
  const current = toLanguage(prefs.preferredLanguage) ?? account.language;
  if (account.languages.length > 1 && current) {
    for (const code of account.languages) {
      select.add(new Option(LANGUAGES[code].name, code, false, code === current));
    }
    (document.getElementById('account-language-name') as HTMLElement).textContent = LANGUAGES[current].name;
    select.addEventListener('change', () => void chooseLanguage(select, current));
  } else {
    (document.getElementById('account-language') as HTMLElement).hidden = true;
  }
  section.hidden = false;
}

/** Switches the language being learned, then re-reads the article in it. */
async function chooseLanguage(select: HTMLSelectElement, previous: Language): Promise<void> {
  const code = toLanguage(select.value);
  if (!code || code === previous) return;
  const name = document.getElementById('account-language-name') as HTMLElement;
  name.textContent = LANGUAGES[code].name;

  const response = await askBackground<{ ok: boolean; error?: string }>({ type: 'SET_LANGUAGE', language: code });
  if (!response?.ok) {
    console.error('Could not change the language:', response?.error ?? 'no response');
    select.value = previous;
    name.textContent = LANGUAGES[previous].name;
    showToast('Couldn’t change the language. Please try again.');
    return;
  }
  // Marks and translations depend on the language, so read the page afresh.
  setPrefs({ preferredLanguage: code }, () => window.location.reload());
}

async function signOut(): Promise<void> {
  if (!(await askBackground({ type: 'SIGN_OUT' }))) {
    showToast('Couldn’t sign out. Please try again.');
    return;
  }
  // The sign-in page keeps its own copy of the session in this origin's
  // localStorage (supabase-js's default storage); without clearing it, it
  // would greet the user as still signed in.
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('sb-') && key.endsWith('-auth-token')) localStorage.removeItem(key);
    }
  } catch (error) {
    console.warn('Could not clear the stored session:', error);
  }
  window.location.reload();
}

type ReaderSettings = {
  fontSize: number;
  lineHeight: number;
  width: number;
  theme: 'light' | 'sepia' | 'dark';
  font: 'serif' | 'sans';
};

const SETTINGS_KEY = 'readerSettings';

/**
 * Settings persist across articles; before, every article reset to 18px
 * light serif. With nothing saved, the theme follows the system, so the
 * reader is not a white flash at night.
 */
function defaultSettings(): ReaderSettings {
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  return { fontSize: useSheets() ? 19 : 18, lineHeight: 1.7, width: 700, theme: dark ? 'dark' : 'light', font: 'serif' };
}

function initSettingsPanel(): void {
  const settingsPanel = document.getElementById('settings-panel') as HTMLElement;
  const close = () => {
    settingsPanel.classList.remove('show');
    document.getElementById('reader-settings')?.setAttribute('aria-expanded', 'false');
  };
  // Tapping outside or Escape closes it, like the word sheets.
  document.addEventListener('click', (e) => {
    if (!settingsPanel.classList.contains('show')) return;
    if ((e.target as HTMLElement).closest('#settings-panel, #reader-settings')) return;
    close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });

  let settings = defaultSettings();
  const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

  const decreaseFontBtn = el<HTMLButtonElement>('decrease-font');
  const increaseFontBtn = el<HTMLButtonElement>('increase-font');
  const decreaseLineHeightBtn = el<HTMLButtonElement>('decrease-line-height');
  const increaseLineHeightBtn = el<HTMLButtonElement>('increase-line-height');
  const decreaseWidthBtn = el<HTMLButtonElement>('decrease-width');
  const increaseWidthBtn = el<HTMLButtonElement>('increase-width');

  function apply() {
    document.body.style.fontSize = `${settings.fontSize}px`;
    el('font-size-value').textContent = `${settings.fontSize}px`;
    decreaseFontBtn.disabled = settings.fontSize <= 14;
    increaseFontBtn.disabled = settings.fontSize >= 26;

    document.documentElement.style.setProperty('--reader-line-height', String(settings.lineHeight));
    el('line-height-value').textContent = settings.lineHeight.toFixed(1);
    decreaseLineHeightBtn.disabled = settings.lineHeight <= 1.3;
    increaseLineHeightBtn.disabled = settings.lineHeight >= 2.2;

    el('reader-container').style.maxWidth = `${settings.width}px`;
    el('width-value').textContent = `${settings.width}px`;
    decreaseWidthBtn.disabled = settings.width <= 500;
    increaseWidthBtn.disabled = settings.width >= 900;

    document.body.classList.remove('theme-light', 'theme-sepia', 'theme-dark');
    if (settings.theme !== 'light') document.body.classList.add(`theme-${settings.theme}`);
    for (const theme of ['light', 'sepia', 'dark'] as const) {
      el(`theme-${theme}`).classList.toggle('active', settings.theme === theme);
      el(`theme-${theme}`).setAttribute('aria-checked', String(settings.theme === theme));
    }
    // Safari tints its toolbar from this.
    const themeColor = { light: '#ffffff', sepia: '#f8f1e3', dark: '#1c1c1e' }[settings.theme];
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themeColor);
    // Safari tints the status-bar strip from the root background, so the
    // dark theme would otherwise sit under a white band.
    document.documentElement.style.backgroundColor = themeColor;

    document.body.classList.toggle('font-sans', settings.font === 'sans');
    el('font-serif').classList.toggle('active', settings.font === 'serif');
    el('font-sans').classList.toggle('active', settings.font === 'sans');
    el('font-serif').setAttribute('aria-checked', String(settings.font === 'serif'));
    el('font-sans').setAttribute('aria-checked', String(settings.font === 'sans'));
  }

  function update(patch: Partial<ReaderSettings>) {
    settings = { ...settings, ...patch };
    apply();
    void chrome.storage.local.set({ [SETTINGS_KEY]: settings });
  }

  const round1 = (n: number) => Math.round(n * 10) / 10;
  decreaseFontBtn.addEventListener('click', () => update({ fontSize: Math.max(14, settings.fontSize - 1) }));
  increaseFontBtn.addEventListener('click', () => update({ fontSize: Math.min(26, settings.fontSize + 1) }));
  decreaseLineHeightBtn.addEventListener('click', () => update({ lineHeight: Math.max(1.3, round1(settings.lineHeight - 0.1)) }));
  increaseLineHeightBtn.addEventListener('click', () => update({ lineHeight: Math.min(2.2, round1(settings.lineHeight + 0.1)) }));
  decreaseWidthBtn.addEventListener('click', () => update({ width: Math.max(500, settings.width - 50) }));
  increaseWidthBtn.addEventListener('click', () => update({ width: Math.min(900, settings.width + 50) }));
  for (const theme of ['light', 'sepia', 'dark'] as const) {
    el(`theme-${theme}`).addEventListener('click', () => update({ theme }));
  }
  el('font-serif').addEventListener('click', () => update({ font: 'serif' }));
  el('font-sans').addEventListener('click', () => update({ font: 'sans' }));

  apply();
  chrome.storage.local.get(SETTINGS_KEY, (result) => {
    const saved = result[SETTINGS_KEY] as Partial<ReaderSettings> | undefined;
    if (saved) {
      settings = { ...settings, ...saved };
      apply();
    }
  });
}
