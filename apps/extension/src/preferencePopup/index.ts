import { supabase } from '../supabaseclient';
import { setPrefs, Prefs, defaultPrefs } from './prefs';
import { sendToActiveTab, sendToBackground } from '../messages';
import { getLanguageInfo, toLanguage, LanguageInfo, type Language } from '../languages';
import type { Session } from '@supabase/supabase-js';
import { getErrorMessage } from '../errors';
import { WEB_URL } from '../config';
import { reviewLink } from '../reviewLink';
import { SIGN_IN_WITH_CODE, normalizeEmailCode, signInWithEmailCode } from '../emailCode';
import { cleanTitle, hostOf } from '../pageTitle';

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

// Safari on iPhone sizes the popup sheet from the page as first laid out.
// Rows that arrive after two round trips push the account row out of the
// sheet, so the last list shown is kept and drawn straight away.
const LANGUAGES_CACHE_KEY = 'popupLanguages';

async function renderCachedLanguageButtons(): Promise<void> {
  try {
    const [cached, prefs] = await Promise.all([
      chrome.storage.local.get(LANGUAGES_CACHE_KEY),
      chrome.storage.sync.get('preferredLanguage'),
    ]);
    const languages = cached[LANGUAGES_CACHE_KEY];
    // The server's answer may have landed first.
    if (!Array.isArray(languages) || languageButtonsContainer.childElementCount) return;
    drawLanguageButtons(languages, prefs.preferredLanguage ?? defaultPrefs.preferredLanguage);
  } catch (err) {
    console.warn('Could not draw cached languages:', err);
  }
}

async function renderLanguageButtons(activeLang: string) {
  try {
    const { data: languages, error } = await supabase.rpc('get_available_languages');
    if (error) throw error;
    if (!Array.isArray(languages)) return;
    void chrome.storage.local.set({ [LANGUAGES_CACHE_KEY]: languages });
    drawLanguageButtons(languages, activeLang);
  } catch (err) {
    console.error('Error fetching languages:', err);
  }
}

function drawLanguageButtons(languages: string[], activeLang: string) {
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
        setReviewLanguage(lang);
      } catch (err) {
        console.error('Error setting default language:', err);
      }
    });
    languageButtonsContainer.appendChild(btn);
  });
}

// --- UI Update Based on Authentication ---
function updateUIForSession(session: Session | null) {
  if (session) {
    // Logged In View
    loggedOutPane.classList.add('hidden');
    loggedInPane.classList.remove('hidden');
    userInfoEl.textContent = session.user.email ?? '';
    void renderCachedLanguageButtons();
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
      setReviewLanguage(activeLang);
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
    if (SIGN_IN_WITH_CODE) codeInput.focus();
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

// The sign-in email also carries a code. Typing it here is the only way to
// sign in on Safari for iOS, where the link cannot reach the extension, so
// only the Safari build shows the code field.
const codeForm = document.getElementById('codeForm') as HTMLFormElement;
const codeInput = document.getElementById('codeInput') as HTMLInputElement;
const codeBtn = document.getElementById('codeBtn') as HTMLButtonElement;
const codeError = document.getElementById('codeError') as HTMLElement;

if (SIGN_IN_WITH_CODE) {
  codeForm.classList.remove('hidden');
  (document.getElementById('sentHint') as HTMLElement).textContent = 'Enter the code from it below.';
}

function showCodeError(message: string | null) {
  codeError.textContent = message ?? '';
  codeError.classList.toggle('hidden', !message);
}

codeForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = sentEmailEl.textContent ?? '';
  const code = normalizeEmailCode(codeInput.value);
  if (!code) {
    showCodeError('Enter the 6-digit code from the email.');
    return;
  }
  showCodeError(null);
  codeBtn.disabled = true;
  try {
    // onAuthStateChange switches to the signed-in view.
    await signInWithEmailCode(email, code);
    showSent(false);
    codeInput.value = '';
  } catch (err: unknown) {
    showCodeError(getErrorMessage(err, 'That code did not work. Please try again.'));
  } finally {
    codeBtn.disabled = false;
  }
});

changeEmailBtn.addEventListener('click', () => {
  showSent(false);
  showCodeError(null);
  codeInput.value = '';
  emailInput.focus();
  emailInput.select();
});

const signUpBtn = document.getElementById('signUpBtn') as HTMLButtonElement;

signUpBtn.addEventListener('click', () => {
  window.open(WEB_URL, '_blank', 'noopener');
});


// Quick links for the signed-in view. chrome.tabs.create opens a normal tab
// and closes the popup, which window.open does not do reliably.
const reviewBtn = document.getElementById('reviewBtn') as HTMLButtonElement;
let reviewUrl = `${WEB_URL}/vocabulary`;
// RemNote reviews open the active language's notes, so the link is redrawn
// when either the settings arrive or the language changes.
let reviewSettings: Parameters<typeof reviewLink>[0] = null;
let reviewLanguage: Language | null = null;

function drawReviewLink() {
  const link = reviewLink(reviewSettings, reviewLanguage);
  reviewUrl = link.url;
  reviewBtn.textContent = link.label;
}

function setReviewLanguage(language: Language) {
  reviewLanguage = language;
  drawReviewLink();
}

async function updateReviewLink(userId: string) {
  const { data, error } = await supabase
    .from('userdata')
    .select('review_provider, remnote_root_rem_id, remnote_language_rem_ids')
    .eq('user_id', userId)
    .maybeSingle();
  if (error) console.error('Could not read review provider:', error);
  reviewSettings = data;
  drawReviewLink();
}

reviewBtn.addEventListener('click', () => {
  chrome.tabs.create({ url: reviewUrl });
});
document.getElementById('openAppBtn')?.addEventListener('click', () => {
  chrome.tabs.create({ url: WEB_URL });
});

// "Read this page" is the popup's main action, signed in or not. The
// keyboard command is the only other way into the reader, and Safari on iOS
// has no extension commands. Opening the popup grants activeTab, which the
// background needs to inject the extraction script into the page.
const readerCard = document.getElementById('readerCard') as HTMLElement;
const readerBtn = document.getElementById('readerBtn') as HTMLButtonElement;
const readerError = document.getElementById('readerError') as HTMLElement;
const readerPageTitle = document.getElementById('readerPageTitle') as HTMLElement;
let readerTabId: number | undefined;

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs[0];
  readerTabId = tab?.id;
  // Without site access the URL can be hidden; still offer the button then.
  const url = tab?.url ?? '';
  const isWebPage = !url || /^https?:/.test(url);
  if (readerTabId === undefined || !isWebPage) return;
  // "Madrid · es.wikipedia.org" rather than the raw <title>, which usually
  // repeats the site ("Madrid - Wikipedia, la enciclopedia libre").
  const host = hostOf(url);
  const title = cleanTitle(tab?.title, host);
  readerPageTitle.textContent = [title, host].filter(Boolean).join(' · ');
  readerCard.classList.remove('hidden');
});

// Extracting the article takes a moment. Closing the popup straight away
// left a page that seemed to ignore the tap, so show progress until the
// background reports the reader is opening (or give up after a while).
const READER_OPEN_TIMEOUT_MS = 10_000;
readerBtn.addEventListener('click', () => {
  if (readerTabId === undefined) {
    readerError.textContent = 'Could not find the current page.';
    readerError.classList.remove('hidden');
    return;
  }
  readerBtn.disabled = true;
  readerBtn.classList.add('loading');
  (document.getElementById('readerBtnTitle') as HTMLElement).textContent = 'Opening…';
  const done = () => window.close();
  const timer = window.setTimeout(done, READER_OPEN_TIMEOUT_MS);
  sendToBackground({ type: 'OPEN_READER', tabId: readerTabId }, () => {
    window.clearTimeout(timer);
    done();
  });
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
