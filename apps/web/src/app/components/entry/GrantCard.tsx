'use client';

import type { OAuthAuthorizationDetails } from '@supabase/supabase-js';
import { ARROW } from './EntryFrame';
import s from './entry.module.css';

const CHECK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </svg>
);

const ALWAYS = [
  'See which words you know and are learning',
  'Record your practice results and the texts you read',
  'Update your progress and schedule reviews, in RemNote too when it’s connected',
];

const SCOPES: Record<string, string> = {
  openid: 'Confirm it’s you',
  email: 'See your email address',
  profile: 'See your name and profile',
};

/** Only the host: enough to recognise the app, short enough to read. */
function host(uri: string) {
  try {
    return new URL(uri).host;
  } catch {
    return uri;
  }
}

/** What an AI app may do with the account, and the choice. */
export default function GrantCard({ details, busy, onDecide }: {
  details: OAuthAuthorizationDetails;
  busy: boolean;
  onDecide: (approve: boolean) => void;
}) {
  const extra = details.scope.split(/\s+/).filter(Boolean).map((scope) => SCOPES[scope] ?? `Account permission: ${scope}`);
  return (
    <div className={s.grant}>
      <ul className={s.can}>
        {[...ALWAYS, ...extra].map((line) => <li key={line}>{CHECK}{line}</li>)}
      </ul>
      <div className={s.meta}>
        <span>Signed in as <b>{details.user.email}</b></span>
        <span title={details.redirect_uri}>Sends you back to <b>{host(details.redirect_uri)}</b></span>
      </div>
      <div className={s.actions}>
        <button type="button" className={s.ghost} disabled={busy} onClick={() => onDecide(false)}>Deny</button>
        <button type="button" className={s.go} disabled={busy} onClick={() => onDecide(true)}>
          {busy ? 'Returning to your app…' : 'Allow access'}
          {!busy && ARROW}
        </button>
      </div>
    </div>
  );
}
