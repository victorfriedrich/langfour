'use client';

import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ARROW, EntryNav, Legal } from './EntryFrame';
import { SkyWall, usePinnedSky } from './Sky';
import s from './entry.module.css';

const MAIL = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="5" width="18" height="14" rx="3" />
    <path d="m4 7 8 6 8-6" />
  </svg>
);

const RESEND_AFTER = 60; // Supabase refuses a second email sooner

/** Gmail's inbox for Gmail addresses, the mail app for the rest. */
export function mailLink(email: string): [string, string] {
  return /@(gmail|googlemail)\.com$/i.test(email.trim())
    ? ['https://mail.google.com', 'Open Gmail']
    : ['mailto:', 'Open Mail'];
}

interface EmailStepProps {
  title: string;
  lead: ReactNode;
  /** The button inside the field. */
  action: string;
  /** What the link does, once it is sent. */
  sentLead: string;
  /** Sends the email; throws with a message to show when it can't. */
  onSend: (email: string) => Promise<void>;
  navRight: ReactNode;
  footer: ReactNode;
}

/** Login and sign-up: one field on the sky's edge, then the address it went to. */
export default function EmailStep({ title, lead, action, sentLead, onSend, navRight, footer }: EmailStepProps) {
  const [email, setEmail] = useState('');
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [wait, setWait] = useState(0);
  const { frame, wall } = usePinnedSky<HTMLElement>([sent]);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const send = async () => {
    setError('');
    setSending(true);
    try {
      await onSend(email.trim());
      setSent(true);
      setWait(RESEND_AFTER);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setSending(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send();
  };

  const [href, openLabel] = mailLink(email);

  return (
    <div className={s.page}>
      <EntryNav right={navRight} />
      <section className={s.band} ref={frame}>
        <SkyWall className={s.wall} wallRef={wall} />
        <h1 className={`${s.title} ${s.in}`} key={sent ? 'sent' : 'ask'}>{sent ? 'Check your email' : title}</h1>
        <p className={`${s.lead} ${s.in2}`}>{sent ? sentLead : lead}</p>
      </section>

      <div className={`${s.edge} ${s.in3}`}>
        {sent ? (
          <div className={s.sent}>
            <span className={s.ic}>{MAIL}</span>
            <span className={s.who}>
              <b>{email}</b>
              <span>Link sent</span>
            </span>
            <a className={s.go} href={href} target="_blank" rel="noopener noreferrer">
              {openLabel}
              {ARROW}
            </a>
          </div>
        ) : (
          <form className={s.pill} onSubmit={submit}>
            <input
              type="email"
              required
              autoFocus
              placeholder="you@example.com"
              aria-label="Email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <button className={s.go} type="submit" disabled={sending}>
              {sending ? 'Sending…' : action}
              {ARROW}
            </button>
          </form>
        )}
      </div>

      <div className={s.below}>
        {error && <p className={s.error} role="alert">{error}</p>}
        {sent ? (
          <p className={s.small}>
            <button type="button" disabled={wait > 0 || sending} onClick={() => void send()}>
              {wait > 0 ? `Send again in ${wait}s` : 'Send again'}
            </button>
            <span className={s.sep}>·</span>
            <button type="button" onClick={() => { setSent(false); setError(''); }}>Use a different email</button>
          </p>
        ) : (
          <p className={s.small}>{footer}</p>
        )}
      </div>
      <Legal />
    </div>
  );
}
