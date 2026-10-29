// The magic link can open in a second tab, so keep the pending destination
// in localStorage. The login tab can resume it without consuming it before
// the callback tab has had a chance to read it.
const KEY = 'after-login';

export function rememberAfterLogin(path: string) {
  try {
    localStorage.setItem(KEY, path);
  } catch {
    // storage unavailable: the user simply lands on the home page
  }
}

export function peekAfterLogin(): string {
  try {
    const path = localStorage.getItem(KEY);
    // Backslashes also become slashes in browser URL parsing.
    if (path && path.startsWith('/') && !path.startsWith('//') && !path.includes('\\')) return path;
  } catch {
    // fall through
  }
  return '/';
}

/** The remembered path, once, and only if it stays on this site. */
export function takeAfterLogin(): string {
  const path = peekAfterLogin();
  try { localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
  return path;
}
