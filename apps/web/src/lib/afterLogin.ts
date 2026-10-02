// Where to go once a magic-link login completes. The link may open in a new
// tab, so this lives in localStorage rather than in the URL or React state.
const KEY = 'after-login';

export function rememberAfterLogin(path: string) {
  try {
    localStorage.setItem(KEY, path);
  } catch {
    // storage unavailable: the user simply lands on the home page
  }
}

/** The remembered path, once, and only if it stays on this site. */
export function takeAfterLogin(): string {
  try {
    const path = localStorage.getItem(KEY);
    localStorage.removeItem(KEY);
    if (path && path.startsWith('/') && !path.startsWith('//')) return path;
  } catch {
    // fall through
  }
  return '/';
}
