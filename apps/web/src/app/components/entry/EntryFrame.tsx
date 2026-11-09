'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import s from './entry.module.css';

export const ARROW = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

/** The landing page's nav: the logo in the same place, links on the right. */
export function EntryNav({ right }: { right?: ReactNode }) {
  return (
    <nav className={s.bar} aria-label="Main">
      <a className={s.brand} href="https://www.langfour.com">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/langfour-logo.svg" alt="" width={28} height={28} />
        <span>Langfour</span>
      </a>
      <div className={s.links}>{right}</div>
    </nav>
  );
}

export function Legal() {
  return (
    <div className={s.legal}>
      <a href="https://www.langfour.com/privacy">Privacy</a>
      <a href="https://www.langfour.com/imprint">Imprint</a>
    </div>
  );
}

export function NewHere() {
  return (
    <>
      <span className={s.muted}>New here?</span>
      <Link className={s.navbtn} href="/get-started">Start learning</Link>
    </>
  );
}

export function HaveAccount() {
  return (
    <>
      <span className={s.muted}>Have an account?</span>
      <Link className={s.lk} href="/login">Log in</Link>
    </>
  );
}
