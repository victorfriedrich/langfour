// Deliberately the shared client rather than a second `createClient` call:
// this page starts a magic-link flow, so it is what writes the PKCE
// `code_verifier` that `auth_handler.html` later needs. A separate client
// here could silently drift back to the default implicit flow and reopen the
// session-fixation hole, so both ends stay on one configuration.
import { supabase } from './supabaseclient';
import { debugLog } from './config';
import { getErrorMessage } from './errors';
import { normalizeEmailCode, signInWithEmailCode } from './emailCode';

// iPadOS reports itself as a Mac; touch support gives it away.
function isIOS(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent)
    || (navigator.userAgent.includes('Macintosh') && navigator.maxTouchPoints > 1);
}

const SENT_TO_KEY = 'signInCodeSentTo';

class LoginForm {
  private form: HTMLFormElement;
  private emailInput: HTMLInputElement;
  private submitButton: HTMLButtonElement;
  private mailPrompt: HTMLDivElement;
  private timerSpan: HTMLSpanElement;
  private retryTimer: number = 60;
  private timerInterval: number | null = null;
  private sentTo: string | null = null;

  constructor() {
    this.form = document.getElementById('login-form') as HTMLFormElement;
    this.emailInput = document.getElementById('email') as HTMLInputElement;
    this.submitButton = document.getElementById('login-btn') as HTMLButtonElement;
    this.mailPrompt = document.getElementById('mail-prompt') as HTMLDivElement;
    this.timerSpan = document.getElementById('timer') as HTMLSpanElement;

    window.addEventListener('message', (event) => {
      if (event.origin === window.location.origin && event.data === 'auth_success') {
        closeThisTab();
      }
    });

    this.initializeEventListeners();

    // First run: the background opens this page with ?welcome after install.
    if (new URLSearchParams(window.location.search).has('welcome')) {
      document.getElementById('heading')!.textContent = 'Welcome to Langfour';
      document.getElementById('subheading')!.textContent = 'Sign in with your email to start saving words.';
      this.showTips();
    }

    // Reinstalling, or opening this page again, while signed in should say
    // so instead of asking for an email.
    void chrome.storage.local.get('supabaseSession').then(({ supabaseSession }) => {
      if (supabaseSession?.access_token) this.showSignedIn(supabaseSession.user?.email ?? null);
    });

    // Reading the code means switching to Mail, and iOS may reload this tab
    // meanwhile. The code is still valid, so keep asking for it.
    const sentTo = this.recallSentTo();
    if (sentTo) {
      this.sentTo = sentTo;
      this.emailInput.value = sentTo;
      this.showCodeForm();
    }
  }

  private showTips() {
    const tips = document.getElementById('welcome-tips');
    tips?.classList.remove('hidden');
    // Safari on iOS has no keyboard shortcut and no subtitle features in
    // this build, so show only the tips that apply.
    const platform = isIOS() ? 'ios' : 'desktop';
    tips?.querySelectorAll<HTMLElement>('[data-platform]').forEach((tip) => {
      tip.classList.toggle('hidden', tip.dataset.platform !== platform);
    });
  }

  private showCodeForm() {
    document.getElementById('code-form')?.classList.remove('hidden');
    document.getElementById('code')?.focus();
  }

  private rememberSentTo(email: string) {
    try {
      sessionStorage.setItem(SENT_TO_KEY, email);
    } catch {
      // Storage blocked: the code form just won't survive a reload.
    }
  }

  private recallSentTo(): string | null {
    try {
      return sessionStorage.getItem(SENT_TO_KEY);
    } catch {
      return null;
    }
  }

  private showSignedIn(email: string | null) {
    document.getElementById('heading')!.textContent = 'You’re signed in';
    document.getElementById('subheading')!.textContent = email ? `as ${email}` : 'You can close this tab.';
    this.form.classList.add('hidden');
    document.getElementById('code-form')?.classList.add('hidden');
    this.mailPrompt.classList.add('hidden');
    this.showTips();
    document.querySelector('.welcome-tips .new-here')?.classList.add('hidden');
  }

  private initializeEventListeners() {
    this.form.addEventListener('submit', (e) => this.handleSubmit(e));
    document
      .getElementById('code-form')
      ?.addEventListener('submit', (e) => this.handleCodeSubmit(e));
    document
      .getElementById('open-mail')
      ?.addEventListener('click', () => this.openMail());
  }

  private async handleSubmit(e: Event) {
    e.preventDefault();
    const email = this.emailInput.value.trim();

    this.showError(null);
    if (!email) {
      this.showError('Please enter your email address.');
      return;
    }

    this.setLoading(true);

    try {
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: chrome.runtime.getURL('src/auth_handler.html'),
        },
      });

      if (error) throw error;

      // Mail apps are a tap away on a phone; the button is for desktop.
      if (!isIOS()) this.mailPrompt.classList.remove('hidden');
      this.startRetryTimer();
      // The code form stays up after the resend timer runs out: the code in
      // the email is still valid until it expires.
      this.sentTo = email;
      this.rememberSentTo(email);
      this.showCodeForm();
    } catch (error) {
      this.showError(getErrorMessage(error, 'Something went wrong. Please try again.'));
      this.setLoading(false);
    }
  }

  private async handleCodeSubmit(e: Event) {
    e.preventDefault();
    const input = document.getElementById('code') as HTMLInputElement;
    const button = document.getElementById('code-btn') as HTMLButtonElement;
    const code = normalizeEmailCode(input.value);

    if (!this.sentTo || !code) {
      this.showCodeError('Enter the 6-digit code from the email.');
      return;
    }

    this.showCodeError(null);
    button.disabled = true;
    try {
      await signInWithEmailCode(this.sentTo, code);
      try {
        sessionStorage.removeItem(SENT_TO_KEY);
      } catch {
        // Nothing to clean up.
      }
      // Safari on iOS may ignore window.close() for a tab the user did not
      // open from script, so leave a finished state behind either way.
      this.stopRetryTimer();
      this.showSignedIn(this.sentTo);
      closeThisTab();
    } catch (error) {
      this.showCodeError(getErrorMessage(error, 'That code did not work. Please try again.'));
    } finally {
      button.disabled = false;
    }
  }

  private showCodeError(message: string | null) {
    const el = document.getElementById('code-error');
    if (!el) return;
    el.textContent = message ?? '';
    el.classList.toggle('hidden', !message);
  }

  private showError(message: string | null) {
    const el = document.getElementById('form-error');
    if (!el) return;
    el.textContent = message ?? '';
    el.classList.toggle('hidden', !message);
  }

  private setLoading(loading: boolean) {
    this.submitButton.disabled = loading;
    if (loading) {
      this.submitButton.classList.add('loading');
    } else {
      this.submitButton.classList.remove('loading');
    }
  }

  private startRetryTimer() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
    }

    this.retryTimer = 60;
    this.updateTimerDisplay();

    this.timerInterval = window.setInterval(() => {
      this.retryTimer--;
      this.updateTimerDisplay();

      if (this.retryTimer <= 0) {
        this.stopRetryTimer();
      }
    }, 1000);
  }

  private stopRetryTimer() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
    this.setLoading(false);
    this.mailPrompt.classList.add('hidden');
  }

  private updateTimerDisplay() {
    this.timerSpan.textContent = this.retryTimer.toString();
  }

  private openMail() {
    const emailProvider = this.emailInput.value.split('@')[1];
    if (emailProvider === 'gmail.com') {
      window.open('https://mail.google.com', '_blank');
    } else {
      window.open('mailto:', '_blank');
    }
  }
}

// Initialize the form when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new LoginForm();
});

// Check auth state when extension loads
export const checkAuthState = async () => {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (session) {
    debugLog('User is signed in');
    // Handle signed-in state
  } else {
    debugLog('No user signed in');
    // Handle signed-out state
  }
};

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
