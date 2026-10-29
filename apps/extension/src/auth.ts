// Deliberately the shared client rather than a second `createClient` call:
// this page starts a magic-link flow, so it is what writes the PKCE
// `code_verifier` that `auth_handler.html` later needs. A separate client
// here could silently drift back to the default implicit flow and reopen the
// session-fixation hole, so both ends stay on one configuration.
import { supabase } from './supabaseclient';
import { getErrorMessage } from './errors';
import { findEmailCode, normalizeEmailCode, signInWithEmailCode } from './emailCode';

// iPadOS reports itself as a Mac; touch support gives it away.
function isIOS(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent)
    || (navigator.userAgent.includes('Macintosh') && navigator.maxTouchPoints > 1);
}

const SENT_TO_KEY = 'signInCodeSentTo';
const RESEND_SECONDS = 60;

const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/**
 * Three steps on one page: the email address, the code from the email, and
 * "signed in". The email also carries a magic link; opening it in this
 * browser finishes sign-in through auth_handler.html instead.
 */
class SignIn {
  private emailForm = el<HTMLFormElement>('login-form');
  private emailInput = el<HTMLInputElement>('email');
  private emailButton = el<HTMLButtonElement>('login-btn');
  private codeForm = el<HTMLFormElement>('code-form');
  private codeInput = el<HTMLInputElement>('code');
  private codeButton = el<HTMLButtonElement>('code-btn');
  private resendButton = el<HTMLButtonElement>('resend');
  private sentTo: string | null = null;
  private resendTimer: number | null = null;
  private heading = el('heading');
  private subheading = el('subheading');
  private emailHeading = '';
  private emailSubheading = '';

  constructor() {
    this.emailForm.addEventListener('submit', (e) => {
      e.preventDefault();
      void this.sendCode(this.emailInput.value.trim());
    });
    this.codeForm.addEventListener('submit', (e) => {
      e.preventDefault();
      void this.verify(this.codeInput.value);
    });
    el('change-email').addEventListener('click', () => this.showEmailStep());
    this.resendButton.addEventListener('click', () => {
      if (this.sentTo) void this.sendCode(this.sentTo);
    });
    el('open-mail').addEventListener('click', () => this.openMail());
    this.initPaste();

    // The magic link, opened in this browser, signs in through another tab.
    window.addEventListener('message', (event) => {
      if (event.origin === window.location.origin && event.data === 'auth_success') closeThisTab();
    });

    // First run: the background opens this page with ?welcome after install.
    if (new URLSearchParams(window.location.search).has('welcome')) {
      this.heading.textContent = 'Welcome to Langfour';
      this.subheading.textContent = 'Sign in to start saving words.';
      this.showTips();
    }
    this.emailHeading = this.heading.textContent ?? '';
    this.emailSubheading = this.subheading.textContent ?? '';

    // Reading the code means switching to Mail, and iOS may reload this tab
    // meanwhile. The code is still valid, so go straight back to it.
    const sentTo = this.recallSentTo();
    if (sentTo) this.showCodeStep(sentTo);

    // Opening this page again while signed in should say so.
    void chrome.storage.local.get('supabaseSession').then(({ supabaseSession }) => {
      if (supabaseSession?.access_token) this.showSignedIn(supabaseSession.user?.email ?? null);
    });
  }

  // --- Steps -------------------------------------------------------------

  private async sendCode(email: string) {
    this.showError('form-error', null);
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      this.showError('form-error', 'Enter your email address.');
      this.emailInput.focus();
      return;
    }

    const resending = this.sentTo === email;
    if (!resending) this.setLoading(this.emailButton, true);
    try {
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: { emailRedirectTo: chrome.runtime.getURL('src/auth_handler.html') },
      });
      if (error) throw error;
      this.rememberSentTo(email);
      this.showCodeStep(email);
    } catch (error) {
      const message = getErrorMessage(error, 'Couldn’t send the email. Try again.');
      if (resending) this.showError('code-error', message);
      else this.showError('form-error', message);
    } finally {
      this.setLoading(this.emailButton, false);
    }
  }

  private async verify(raw: string) {
    const code = normalizeEmailCode(raw);
    if (!this.sentTo || !code) {
      this.showError('code-error', this.codeInput.value.trim() ? 'Enter the full code from the email.' : 'Enter the code from the email.');
      this.codeInput.focus();
      return;
    }

    this.showError('code-error', null);
    this.setLoading(this.codeButton, true);
    try {
      await signInWithEmailCode(this.sentTo, code);
      this.forgetSentTo();
      this.showSignedIn(this.sentTo);
      // Safari on iOS may ignore closing a tab the user did not open from
      // script, so the finished state above stays as the fallback.
      closeThisTab();
    } catch (error) {
      const message = getErrorMessage(error, '');
      // Supabase says "Token has expired or is invalid".
      this.showError('code-error', /expired|invalid/i.test(message) || !message
        ? 'That code is wrong or has expired. Check the latest email.'
        : message);
      this.codeInput.select();
    } finally {
      this.setLoading(this.codeButton, false);
    }
  }

  private showEmailStep() {
    this.forgetSentTo();
    this.sentTo = null;
    this.stopResendTimer();
    this.codeForm.classList.add('hidden');
    this.emailForm.classList.remove('hidden');
    this.heading.textContent = this.emailHeading;
    this.subheading.textContent = this.emailSubheading;
    this.emailInput.focus();
  }

  private showCodeStep(email: string) {
    this.sentTo = email;
    this.emailInput.value = email;
    el('sent-email').textContent = email;
    this.heading.textContent = 'Check your email';
    this.subheading.textContent = 'Enter the code we sent you.';
    this.emailForm.classList.add('hidden');
    this.codeForm.classList.remove('hidden');
    // The Gmail shortcut only helps on a desktop; a phone has the Mail app.
    el('open-mail').classList.toggle('hidden', isIOS() || !email.endsWith('@gmail.com'));
    this.codeInput.value = '';
    this.codeInput.focus();
    this.startResendTimer();
  }

  private showSignedIn(email: string | null) {
    this.stopResendTimer();
    document.body.classList.add('is-signed-in');
    this.heading.textContent = 'You’re signed in';
    this.subheading.classList.add('hidden');
    this.emailForm.classList.add('hidden');
    this.codeForm.classList.add('hidden');
    el('signed-in').classList.remove('hidden');
    el('signed-in-email').textContent = email ?? '';
    document.querySelector('.new-here')?.classList.add('hidden');
    this.showTips();
  }

  private showTips() {
    const tips = el('welcome-tips');
    tips.classList.remove('hidden');
    const platform = isIOS() ? 'ios' : 'desktop';
    tips.querySelectorAll<HTMLElement>('[data-platform]').forEach((tip) => {
      tip.classList.toggle('hidden', tip.dataset.platform !== platform);
    });
  }

  // --- Pasting the code ----------------------------------------------------

  /**
   * The code arrives by email, so it is usually pasted: alone, as the
   * subject line, or as a chunk of the email. Any of those fills in just the
   * code and signs in. So does iOS's AutoFill from Mail, which inserts the
   * whole code at once.
   */
  private initPaste() {
    this.codeInput.addEventListener('paste', (event) => {
      const code = findEmailCode(event.clipboardData?.getData('text') ?? '');
      if (!code) return;
      event.preventDefault();
      this.fillAndVerify(code);
    });

    this.codeInput.addEventListener('input', (event) => {
      this.showError('code-error', null);
      const typedOneDigit = (event as InputEvent).inputType === 'insertText';
      const code = normalizeEmailCode(this.codeInput.value);
      if (code && !typedOneDigit) this.fillAndVerify(code);
    });

    // Reading the clipboard needs the async Clipboard API; without it the
    // field's own paste still works.
    const pasteButton = el<HTMLButtonElement>('paste-code');
    if (!navigator.clipboard?.readText) return;
    pasteButton.classList.remove('hidden');
    pasteButton.addEventListener('click', async () => {
      try {
        const code = findEmailCode(await navigator.clipboard.readText());
        if (code) this.fillAndVerify(code);
        else this.showError('code-error', 'No code on the clipboard. Copy the code from the email first.');
      } catch {
        // Declined or not allowed: let the field take a normal paste.
        this.codeInput.focus();
      }
    });
  }

  private fillAndVerify(code: string) {
    this.codeInput.value = code;
    void this.verify(code);
  }

  // --- Helpers -------------------------------------------------------------

  private startResendTimer() {
    this.stopResendTimer();
    let seconds = RESEND_SECONDS;
    const render = () => {
      this.resendButton.disabled = seconds > 0;
      this.resendButton.textContent = seconds > 0 ? `Resend code in ${seconds} s` : 'Resend code';
    };
    render();
    this.resendTimer = window.setInterval(() => {
      seconds -= 1;
      render();
      if (seconds <= 0) this.stopResendTimer();
    }, 1000);
  }

  private stopResendTimer() {
    if (this.resendTimer !== null) window.clearInterval(this.resendTimer);
    this.resendTimer = null;
  }

  private setLoading(button: HTMLButtonElement, loading: boolean) {
    button.disabled = loading;
    button.classList.toggle('loading', loading);
  }

  private showError(id: 'form-error' | 'code-error', message: string | null) {
    const error = el(id);
    error.textContent = message ?? '';
    error.classList.toggle('hidden', !message);
  }

  private openMail() {
    window.open('https://mail.google.com', '_blank', 'noopener');
  }

  private rememberSentTo(email: string) {
    try {
      sessionStorage.setItem(SENT_TO_KEY, email);
    } catch {
      // Storage blocked: the code step just won't survive a reload.
    }
  }

  private recallSentTo(): string | null {
    try {
      return sessionStorage.getItem(SENT_TO_KEY);
    } catch {
      return null;
    }
  }

  private forgetSentTo() {
    try {
      sessionStorage.removeItem(SENT_TO_KEY);
    } catch {
      // Nothing to clean up.
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  new SignIn();
});

// Safari on iOS ignores window.close() for this tab, so it stayed open and
// became the page Safari showed next time. An extension page may close its
// own tab through the tabs API; window.close() covers the popup-window case.
function closeThisTab() {
  if (chrome.tabs?.getCurrent) {
    chrome.tabs.getCurrent((tab) => {
      if (tab?.id !== undefined) void chrome.tabs.remove(tab.id);
      else window.close();
    });
  } else {
    window.close();
  }
}
