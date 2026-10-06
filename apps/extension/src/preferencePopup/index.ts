import { supabase } from '../supabaseclient';
import { setPrefs, Prefs, defaultPrefs } from './prefs';
import { sendToActiveTab } from '../messages';
import { getLanguageInfo, toLanguage, LanguageInfo } from '../languages';
import type { Session } from '@supabase/supabase-js';
import { getErrorMessage } from '../errors';
import { WEB_URL } from '../config';

// --- DOM Elements for Logged In View ---
const loggedInPane = document.getElementById('loggedInPane') as HTMLElement;
const languageButtonsContainer = document.getElementById('languageButtons') as HTMLElement;
const userInfoEl = document.getElementById('userInfo') as HTMLElement;
const logoutBtn = document.getElementById('logoutBtn') as HTMLButtonElement;
const versionEl = document.getElementById('version') as HTMLElement;

// --- DOM Elements for Logged Out (Login) View ---
const loggedOutPane = document.getElementById('loggedOutPane') as HTMLElement;
const loginForm = document.getElementById('loginForm') as HTMLFormElement;
const emailInput = document.getElementById('email') as HTMLInputElement;
const loginBtn = document.getElementById('loginBtn') as HTMLButtonElement;
const loginError = document.getElementById('loginError') as HTMLElement;



// Set version text from manifest
const extensionVersion = chrome.runtime.getManifest().version;
versionEl.textContent = `v${extensionVersion}`;

// Helper: send message to active tab about prefs update
function sendPrefsUpdate() {
  sendToActiveTab({ type: 'PREFS_UPDATED' });
}

// --- Language Buttons Rendering (Logged In View) ---
async function renderLanguageButtons(activeLang: string) {
  try {
    const { data: languages, error } = await supabase.rpc('get_available_languages');
    if (error) throw error;
    if (!Array.isArray(languages)) return;

    // Normalise before rendering, and drop anything unrecognised. Previously
    // each entry went straight to `flagcdn.com/${lang}.svg` and
    // `Intl.DisplayNames`; a legacy long name is a structurally valid language
    // subtag, so DisplayNames echoed it back rather than throwing and the row
    // rendered as a lowercase "spanish" beside a 404ing flag.
    const activeCode = toLanguage(activeLang);
    const infos = languages
      .map((lang: string) => getLanguageInfo(lang))
      .filter((info): info is LanguageInfo => info !== null);
    const seen = new Set<string>();

    languageButtonsContainer.innerHTML = '';
    infos.forEach((info) => {
      // Legacy rows can list the same language more than once.
      if (seen.has(info.code)) return;
      seen.add(info.code);

      const btn = document.createElement('div');
      btn.className = 'language-button' + (info.code === activeCode ? ' active' : '');
      btn.dataset.lang = info.code;
      btn.setAttribute('role', 'radio');
      btn.setAttribute('aria-checked', String(info.code === activeCode));
      btn.tabIndex = 0;
      const flag = document.createElement('img');
      flag.src = `https://flagcdn.com/${info.flag}.svg`;
      flag.width = 28;
      flag.className = 'language-flag';
      flag.alt = info.name;
      const label = document.createElement('span');
      label.textContent = info.name;
      btn.append(flag, label);
      const lang = info.code;
      btn.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          btn.click();
        }
      });
      btn.addEventListener('click', async () => {
        // Update active button state
        document.querySelectorAll('.language-button').forEach((el) => {
          el.classList.remove('active');
          el.setAttribute('aria-checked', 'false');
        });
        btn.classList.add('active');
        btn.setAttribute('aria-checked', 'true');
        try {
          // Call Supabase RPC to update default language
          const { error } = await supabase.rpc('set_user_default_language', { _language: lang });
          if (error) throw error;
          // Update local chrome storage prefs and notify content script.
          // No @ts-ignore needed now that `lang` is a Language, not a string.
          const newPrefs: Prefs = { preferredLanguage: lang };
          setPrefs(newPrefs, () => {
            sendPrefsUpdate();
          });
        } catch (err) {
          console.error('Error setting default language:', err);
        }
      });
      languageButtonsContainer.appendChild(btn);
    });
  } catch (err) {
    console.error('Error fetching languages:', err);
  }
}

// --- UI Update Based on Authentication ---
function updateUIForSession(session: Session | null) {
  if (session) {
    // Logged In View
    loggedOutPane.classList.add('hidden');
    loggedInPane.classList.remove('hidden');
    userInfoEl.textContent = session.user.email ?? '';
    void updateReviewLink(session.user.id);
    supabase.rpc('get_user_default_language').then(({ data, error }) => {
      if (error) {
        console.error('Error getting default language:', error);
        return;
      }
      const activeLang = toLanguage(typeof data === 'string' ? data : null);
      if (!activeLang) {
        console.error('No valid default language returned');
        renderLanguageButtons(defaultPrefs.preferredLanguage);
        return;
      }

      // Reconcile the local mirror after login. This repairs installs where
      // an older version persisted the transient Spanish fallback.
      setPrefs({ preferredLanguage: activeLang }, sendPrefsUpdate);
      renderLanguageButtons(activeLang);
    });
  } else {
    // Logged Out View
    loggedInPane.classList.add('hidden');
    loggedOutPane.classList.remove('hidden');
  }
}

// Listen for auth state changes
supabase.auth.onAuthStateChange((_event, session) => {
  updateUIForSession(session);
});

// Check session on popup load
supabase.auth.getSession().then(({ data: { session } }) => {
  updateUIForSession(session);
});

// --- Login / Magic Link Flow ---
// Three states: the form, "Sending…" on the button, then a "check your email"
// panel with a resend countdown in place of the form.
const RESEND_SECONDS = 60;
const sentEmailEl = document.getElementById('sentEmail') as HTMLElement;
const resendBtn = document.getElementById('resendBtn') as HTMLButtonElement;
const changeEmailBtn = document.getElementById('changeEmailBtn') as HTMLButtonElement;
let timerInterval: number | null = null;

function showLoginError(message: string | null) {
  loginError.textContent = message ?? '';
  loginError.classList.toggle('hidden', !message);
}

function setSending(sending: boolean) {
  loginBtn.disabled = sending;
  loginBtn.classList.toggle('loading', sending);
}

function showSent(sent: boolean) {
  loggedOutPane.classList.toggle('sent', sent);
  if (!sent && timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

function startResendCountdown() {
  if (timerInterval) clearInterval(timerInterval);
  let secondsLeft = RESEND_SECONDS;
  resendBtn.disabled = true;
  resendBtn.innerHTML = 'Resend in <span id="timer"></span>s';
  const tick = () => {
    (document.getElementById('timer') as HTMLElement).textContent = String(secondsLeft);
    if (secondsLeft <= 0) {
      clearInterval(timerInterval!);
      timerInterval = null;
      resendBtn.disabled = false;
      resendBtn.textContent = 'Resend link';
    }
    secondsLeft--;
  };
  tick();
  timerInterval = window.setInterval(tick, 1000);
}

async function sendMagicLink(email: string) {
  setSending(true);
  showLoginError(null);
  try {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: chrome.runtime.getURL('src/auth_handler.html')
      }
    });
    if (error) throw error;
    sentEmailEl.textContent = email;
    showSent(true);
    startResendCountdown();
  } catch (err: unknown) {
    showSent(false);
    showLoginError(getErrorMessage(err, 'Something went wrong. Please try again.'));
  } finally {
    setSending(false);
  }
}

// Handle login form submission
loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  if (!email) {
    showLoginError('Please enter your email address.');
    return;
  }
  await sendMagicLink(email);
});

resendBtn.addEventListener('click', () => {
  const email = sentEmailEl.textContent ?? '';
  if (!email) return;
  resendBtn.disabled = true;
  resendBtn.textContent = 'Sending…';
  void sendMagicLink(email);
});

changeEmailBtn.addEventListener('click', () => {
  showSent(false);
  emailInput.focus();
  emailInput.select();
});

const signUpBtn = document.getElementById('signUpBtn') as HTMLButtonElement;

signUpBtn.addEventListener('click', () => {
  window.open(WEB_URL, '_blank', 'noopener');
});

document.querySelectorAll('#version, #version-login').forEach(el => {
  el.textContent = `v${extensionVersion}`;
});

// Quick links for the signed-in view. chrome.tabs.create opens a normal tab
// and closes the popup, which window.open does not do reliably.
// Reviews happen in RemNote when the user switched scheduling to it
// (userdata.review_provider, same as the web app's TodayCard). The link opens
// the review queue of their "Langfour" document, which the RemNote plugin
// reports; RemNote's home page until it has synced once.
const remnoteUrl = (rootRemId: unknown) =>
  typeof rootRemId === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(rootRemId)
    ? `https://www.remnote.com/flashcards/${rootRemId}`
    : 'https://www.remnote.com/';
const reviewBtn = document.getElementById('reviewBtn') as HTMLButtonElement;
let reviewUrl = `${WEB_URL}/vocabulary`;

async function updateReviewLink(userId: string) {
  const { data, error } = await supabase
    .from('userdata')
    .select('review_provider, remnote_root_rem_id')
    .eq('user_id', userId)
    .maybeSingle();
  if (error) console.error('Could not read review provider:', error);
  const remnote = data?.review_provider === 'remnote';
  reviewUrl = remnote ? remnoteUrl(data?.remnote_root_rem_id) : `${WEB_URL}/vocabulary`;
  reviewBtn.textContent = remnote ? 'Review in RemNote' : 'Review flashcards';
}

reviewBtn.addEventListener('click', () => {
  chrome.tabs.create({ url: reviewUrl });
});
document.getElementById('openAppBtn')?.addEventListener('click', () => {
  chrome.tabs.create({ url: WEB_URL });
});

// Logout button event
logoutBtn.addEventListener('click', async () => {
  const { error } = await supabase.auth.signOut();
  if (error) {
    console.error('Error signing out:', error);
  }

  // signOut() only clears *this* context's storage. The background service
  // worker has no persistent storage of its own and rehydrates from
  // `supabaseSession` in chrome.storage.local on every wake-up, so leaving it
  // behind means the worker keeps presenting tokens that signOut() just
  // revoked server-side. Clear it here regardless of `error`: a failed
  // sign-out request may still have revoked the session.
  await chrome.storage.local.remove('supabaseSession');
});
