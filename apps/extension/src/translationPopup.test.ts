import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getPopupHTML, getSignInPromptHTML, getTranslationHTML } from './markup';
import addMouseEnterLeaveEventListeners, { positionElement } from './utils';

function render(html: string): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host;
}

const translation = { id: 7, root: 'ir', translation: 'go' };

describe('getTranslationHTML', () => {
  it('shows the dictionary form over the translation, without the tapped form', () => {
    const popup = render(getTranslationHTML([translation], 'vas', true));
    expect(popup.querySelector('.sub-tr-dict-item-root')?.textContent).toBe('ir');
    expect(popup.querySelector('.sub-tr-dict-item-text')?.textContent).toBe('go');
    expect(popup.textContent).not.toContain('vas');
  });

  it('falls back to the tapped form when there is no dictionary form', () => {
    const popup = render(getTranslationHTML([{ ...translation, root: '' }], 'vas', true));
    expect(popup.querySelector('.sub-tr-dict-item-root')?.textContent).toBe('vas');
    expect(popup.querySelector('.sub-tr-plus-button')?.getAttribute('aria-label')).toBe('Add vas to flashcards');
  });

  it('names the word on the "+" button', () => {
    const button = render(getTranslationHTML([translation], 'vas', true)).querySelector('.sub-tr-plus-button');
    expect(button?.getAttribute('aria-label')).toBe('Add ir to flashcards');
    expect(button?.getAttribute('data-id')).toBe('7');
  });

  // move_words_to_userwords resets a saved word to learning and drops its
  // RemNote notes, so the "+" must never reach one.
  it('offers no "+" for a saved word', () => {
    expect(render(getTranslationHTML([translation], 'vas', false)).querySelector('button')).toBeNull();
  });

  it('offers no "+" when there is nothing to save', () => {
    expect(render(getTranslationHTML([{ ...translation, id: 0 }], 'vas', true)).querySelector('button')).toBeNull();
  });

  it('escapes what the API returns', () => {
    const popup = render(getTranslationHTML([{ id: 7, root: '<b>ir</b>', translation: '<i>go</i>' }], 'vas', true));
    expect(popup.querySelector('b, i')).toBeNull();
    expect(popup.querySelector('.sub-tr-dict-item-root')?.textContent).toBe('<b>ir</b>');
  });
});

describe('the other popup states', () => {
  it('loads without showing a word that the dictionary form would replace', () => {
    const popup = render(getPopupHTML());
    expect(popup.textContent?.trim()).toBe('');
    expect(popup.querySelector('[role="status"]')?.getAttribute('aria-label')).toBe('Translating');
  });

  it('asks a signed-out user to sign in', () => {
    const popup = render(getSignInPromptHTML('vas'));
    expect(popup.querySelector('.sub-tr-dict-item-root')?.textContent).toBe('vas');
    expect(popup.querySelector('.sub-tr-sign-in-button')?.textContent).toBe('Sign in');
  });
});

describe('positionElement', () => {
  const rect = (left: number, top: number, width: number, height: number) =>
    ({ left, top, width, height, right: left + width, bottom: top + height }) as DOMRect;
  const element = (r: DOMRect) => {
    const el = document.createElement('div');
    el.getBoundingClientRect = () => r;
    return el;
  };

  // Its containing block starts at `origin`: (0, 0) is the viewport, anything
  // else a transformed ancestor.
  function place(popupSize: [number, number], word: DOMRect, player: DOMRect, origin = { left: 0, top: 0 }) {
    const popup = document.createElement('div');
    popup.getBoundingClientRect = () =>
      rect(
        (parseFloat(popup.style.left) || 0) + origin.left,
        (parseFloat(popup.style.top) || 0) + origin.top,
        ...popupSize,
      );
    positionElement(popup, element(word), element(player));
    return popup.getBoundingClientRect();
  }

  const player = rect(100, 100, 800, 450);

  it('centres the popup above the word', () => {
    expect(place([220, 69], rect(500, 500, 40, 30), player)).toMatchObject({ left: 410, top: 423 });
  });

  it('keeps it inside the player at either edge', () => {
    expect(place([220, 69], rect(105, 500, 40, 30), player).left).toBe(108);
    expect(place([220, 69], rect(860, 500, 30, 30), player).left).toBe(672);
  });

  it('keeps its start on screen in a player narrower than the popup', () => {
    expect(place([220, 69], rect(50, 150, 40, 20), rect(0, 0, 160, 90)).left).toBe(8);
  });

  it('lands in the same place inside a transformed ancestor', () => {
    const inside = place([220, 69], rect(500, 500, 40, 30), player, { left: 0, top: 39 });
    expect(inside).toMatchObject({ left: 410, top: 423 });
  });

  it('stays on screen when the page has scrolled the player partly out of view', () => {
    const { top } = place([220, 69], rect(500, 40, 40, 30), rect(100, -300, 800, 450));
    expect(top).toBeGreaterThanOrEqual(8);
  });
});

describe('hovering caption words', () => {
  const word = document.createElement('span');
  word.className = 'word';
  const otherWord = document.createElement('span');
  otherWord.className = 'word';
  const popup = document.createElement('div');
  popup.className = 'popup';
  const events: string[] = [];
  let under: Element[] = [];

  const pointAt = (...elements: Element[]) => {
    under = elements;
    document.dispatchEvent(new MouseEvent('mousemove', { clientX: 1, clientY: 1 }));
    vi.advanceTimersByTime(16);
  };

  let added: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    document.elementsFromPoint = () => under;
    added = vi.spyOn(document, 'addEventListener');
    addMouseEnterLeaveEventListeners({
      selector: '.word',
      ignoreElClassName: 'popup',
      onEnter: (el) => events.push(`enter ${el === word ? 'word' : 'other'}`),
      onLeave: (el) => events.push(`leave ${el === word ? 'word' : 'other'}`),
    });
    pointAt(word);
    events.length = 0;
  });

  afterEach(() => {
    const [type, listener] = added.mock.calls[0] as [string, EventListener];
    document.removeEventListener(type, listener);
    added.mockRestore();
    vi.useRealTimers();
  });

  it('keeps the popup open while the pointer crosses the gap and other words on its way there', () => {
    pointAt();
    pointAt(otherWord);
    pointAt();
    pointAt(popup);
    vi.advanceTimersByTime(1000);
    expect(events).toEqual([]);
  });

  it('closes once the pointer rests away from the word', () => {
    pointAt();
    vi.advanceTimersByTime(1000);
    expect(events).toEqual(['leave word']);
  });

  it('moves to another word once the pointer rests on it', () => {
    pointAt(otherWord);
    vi.advanceTimersByTime(1000);
    expect(events).toEqual(['leave word', 'enter other']);
  });

  it('stays open when the pointer comes back to the word', () => {
    pointAt();
    pointAt(word);
    vi.advanceTimersByTime(1000);
    expect(events).toEqual([]);
  });
});
