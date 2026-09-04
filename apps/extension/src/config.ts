const DEFAULT_BACKEND_URL =
  'https://major-wynny-victorfriedrich-7c04e8cd.koyeb.app';

const configuredBackendUrl = process.env.REACT_APP_BACKEND_URL?.trim();

/**
 * Shared backend origin for every extension execution context.
 *
 * Parcel replaces the environment variable at build time. The deployed
 * backend remains the default so production builds keep working when no
 * local .env file is present.
 */
export const BACKEND_URL = (configuredBackendUrl || DEFAULT_BACKEND_URL).replace(
  /\/+$/,
  '',
);

const DEFAULT_WEB_APP_URL = 'https://app.langfour.com';

const configuredWebAppUrl = process.env.REACT_APP_WEB_APP_URL?.trim();

/**
 * Public web app origin, used for sign-up and any other link out of the
 * popup. Resolved the same way as BACKEND_URL so a local build can point at
 * a dev server without editing source.
 */
export const WEB_APP_URL = (configuredWebAppUrl || DEFAULT_WEB_APP_URL).replace(
  /\/+$/,
  '',
);

const DEBUG_ENABLED = process.env.REACT_APP_DEBUG === 'true';

/** Keep routine diagnostics out of production consoles. */
export function debugLog(...data: unknown[]): void {
  if (DEBUG_ENABLED) {
    console.debug(...data);
  }
}
