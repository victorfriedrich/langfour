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

const DEBUG_ENABLED = process.env.REACT_APP_DEBUG === 'true';

/** Keep routine diagnostics out of production consoles. */
export function debugLog(...data: unknown[]): void {
  if (DEBUG_ENABLED) {
    console.debug(...data);
  }
}
