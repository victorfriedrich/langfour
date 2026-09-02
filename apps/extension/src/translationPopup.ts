import {
  getPopupHTML,
  getTranslationHTML,
  subLoadingClassName,
  subPopupClassName,
  subPopupWrapperClassName,
} from './markup';
import translationPopupStyles from 'bundle-text:./translationPopup.css';
import { positionElement } from './utils';
import { sanitizeHTML } from './sanitizeHTML';
import { Translation } from './translate';

export function insertTranslationPopup(
  targetEl: HTMLElement,
  containerEl: HTMLElement,
  offsetBottom: number,
  onClose: () => void,
): HTMLElement {
  const shadowDomWrapperEl = document.createElement('div');
  shadowDomWrapperEl.classList.add(subPopupWrapperClassName);
  const shadow = shadowDomWrapperEl.attachShadow({ mode: 'open' });
  const styleEl = document.createElement('style');
  styleEl.textContent = translationPopupStyles as unknown as string;

  shadow.innerHTML = sanitizeHTML(getPopupHTML(offsetBottom));
  shadow.appendChild(styleEl);
  containerEl.appendChild(shadowDomWrapperEl);

  const popupEl = shadow.querySelector(`.${subPopupClassName}`) as HTMLElement;
  positionElement(popupEl, targetEl, containerEl);
  popupEl.querySelector('.sub-tr-plus-button')?.addEventListener('click', onClose);
  return popupEl;
}

function postToContentScript(data: { wordId: string }) {
  window.postMessage({
    source: 'translationPopup',
    payload: data
  }, '*');
}

export function insertTranslationResult(
  translationPopupEl: HTMLElement,
  translations: Translation,
  hideTranslationPopup: () => void
) {
  const html = getTranslationHTML([translations]);
  const loaderEl = translationPopupEl.querySelector(`.${subLoadingClassName}`);
  loaderEl?.insertAdjacentHTML('afterend', sanitizeHTML(html));
  loaderEl?.remove();

  // Attach event listeners to the new buttons
  translationPopupEl.querySelectorAll('.sub-tr-plus-button').forEach(button => {
    button.addEventListener('click', async () => {
      const wordId = button.getAttribute('data-id');
      if (wordId) {
        hideTranslationPopup();
        postToContentScript({ wordId });

      } else {
        console.error('No word ID found');
      }
    });
  });
}

export function hideTranslationPopup() {
  const popupEl = document.querySelector(`.${subPopupWrapperClassName}`);
  popupEl?.remove();
}
