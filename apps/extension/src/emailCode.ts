// Signing in with the code from the sign-in email, as an alternative to the
// magic link. The link redirects to an extension page, which works in desktop
// Chrome but not in Safari on iOS: there the extension's origin carries a
// per-install UUID that Supabase's redirect allowlist cannot list, and Mail
// cannot open an extension URL anyway. Typing the code into the extension
// needs no redirect at all.
//
// The same email carries both. Supabase only includes the code if the
// project's "Magic Link" email template contains {{ .Token }}.
import type { Session } from '@supabase/supabase-js';
import { supabase } from './supabaseclient';
import { sendToBackground } from './messages';

/** Supabase's email OTP length is configurable from 6 to 10 digits. */
export function normalizeEmailCode(raw: string): string | null {
  const digits = raw.replace(/\s+/g, '');
  return /^\d{6,10}$/.test(digits) ? digits : null;
}

/**
 * Exchanges the emailed code for a session and hands it to the background,
 * the same way auth_handler.ts does after a magic link. Throws with the
 * Supabase message (e.g. "Token has expired or is invalid") on failure.
 */
export async function signInWithEmailCode(email: string, code: string): Promise<Session> {
  const { data, error } = await supabase.auth.verifyOtp({ email, token: code, type: 'email' });
  if (error) throw error;
  if (!data.session) throw new Error('Sign-in did not return a session. Please try again.');

  const session = data.session;
  await chrome.storage.local.set({ supabaseSession: session });
  await new Promise<void>((resolve) => {
    sendToBackground({ type: 'AUTH_SUCCESS', session }, () => resolve());
  });
  return session;
}
