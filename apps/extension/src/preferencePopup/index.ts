import { supabase } from '../supabaseclient';
import { setPrefs, Prefs, defaultPrefs } from './prefs';
import { sendToActiveTab } from '../messages';
import { getLanguageInfo, toLanguage, LanguageInfo } from '../languages';
import type { Session } from '@supabase/supabase-js';
import { getErrorMessage } from '../errors';
import { WEB_APP_URL } from '../config';

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
const timerSpan = document.getElementById('timer') as HTMLElement;
const progressCircle = document.querySelector<SVGCircleElement>('#progress-circle')!;



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
      const flag = document.createElement('img');
      flag.src = `https://flagcdn.com/${info.flag}.svg`;
      flag.width = 28;
      flag.className = 'language-flag';
      flag.alt = info.name;
      const label = document.createElement('span');
      label.textContent = info.name;
      btn.append(flag, label);
      const lang = info.code;
      btn.addEventListener('click', async () => {
        // Update active button state
        document.querySelectorAll('.language-button').forEach((el) =>
          el.classList.remove('active')
        );
        btn.classList.add('active');
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
let retryTimer = 60;
let timerInterval: number | null = null;
const TOTAL_SECONDS = 60;

function setLoading(loading: boolean) {
  loginBtn.disabled = loading;
  if (loading) {
    loginBtn.classList.add('loading');
  } else {
    loginBtn.classList.remove('loading');
    // Reset progress circle
    updateProgressCircle(TOTAL_SECONDS);
  }
}

function updateTimerDisplay() {
  timerSpan.textContent = retryTimer.toString();
}

function updateProgressCircle(secondsLeft: number) {
  // SVG circle has a circumference of 2πr = 2π*9 = ~56.55
  // We use 60 as approx dasharray value for simplicity
  const dashOffset = (secondsLeft / TOTAL_SECONDS) * 60;
  progressCircle.style.strokeDashoffset = dashOffset.toString();
}

function startRetryTimer() {
  if (timerInterval) clearInterval(timerInterval);
  retryTimer = 60;
  updateTimerDisplay();
  timerInterval = window.setInterval(() => {
    retryTimer--;
    updateTimerDisplay();
    if (retryTimer <= 0) {
      stopRetryTimer();
    }
  }, 1000);
}

function stopRetryTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
  setLoading(false);
}

async function sendMagicLink(email: string) {
  setLoading(true);
  try {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: chrome.runtime.getURL('src/auth_handler.html')
      }
    });
    if (error) throw error;
    startRetryTimer();
  } catch (err: unknown) {
    alert(getErrorMessage(err, 'An unexpected error occurred'));
    setLoading(false);
  }
}

// Handle login form submission
loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  if (!email) {
    alert('Please enter a valid email');
    return;
  }
  await sendMagicLink(email);
});

const signUpBtn = document.getElementById('signUpBtn') as HTMLButtonElement;

signUpBtn.addEventListener('click', () => {
  window.open(WEB_APP_URL, '_blank');
});

document.querySelectorAll('#version').forEach(el => {
  el.textContent = `v${extensionVersion}`;
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
