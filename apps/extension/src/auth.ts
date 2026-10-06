// Deliberately the shared client rather than a second `createClient` call:
// this page starts a magic-link flow, so it is what writes the PKCE
// `code_verifier` that `auth_handler.html` later needs. A separate client
// here could silently drift back to the default implicit flow and reopen the
// session-fixation hole, so both ends stay on one configuration.
import { supabase } from './supabaseclient';
import { debugLog } from './config';
import { getErrorMessage } from './errors';

class LoginForm {
  private form: HTMLFormElement;
  private emailInput: HTMLInputElement;
  private submitButton: HTMLButtonElement;
  private mailPrompt: HTMLDivElement;
  private timerSpan: HTMLSpanElement;
  private retryTimer: number = 60;
  private timerInterval: number | null = null;

  constructor() {
    this.form = document.getElementById('login-form') as HTMLFormElement;
    this.emailInput = document.getElementById('email') as HTMLInputElement;
    this.submitButton = document.getElementById('login-btn') as HTMLButtonElement;
    this.mailPrompt = document.getElementById('mail-prompt') as HTMLDivElement;
    this.timerSpan = document.getElementById('timer') as HTMLSpanElement;

    window.addEventListener('message', (event) => {
      if (event.origin === window.location.origin && event.data === 'auth_success') {
        window.close();
      }
    });

    this.initializeEventListeners();

    // First run: the background opens this page with ?welcome after install.
    if (new URLSearchParams(window.location.search).has('welcome')) {
      document.getElementById('heading')!.textContent = 'Welcome to Langfour';
      document.getElementById('subheading')!.textContent = 'Sign in with your email to start saving words.';
      document.getElementById('welcome-tips')?.classList.remove('hidden');
    }
  }

  private initializeEventListeners() {
    this.form.addEventListener('submit', (e) => this.handleSubmit(e));
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

      this.mailPrompt.classList.remove('hidden');
      this.startRetryTimer();
    } catch (error) {
      this.showError(getErrorMessage(error, 'Something went wrong. Please try again.'));
      this.setLoading(false);
    }
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
