'use client';

import type { ReactNode } from 'react';
import { EntryNav, Legal } from './EntryFrame';
import { SkyWall, usePinnedSky } from './Sky';
import s from './entry.module.css';

/** The sky band with a title, and whatever sits on its edge. */
export default function SkyFrame({ title, lead, children, state }: {
  title: ReactNode;
  lead: ReactNode;
  children?: ReactNode;
  /** Changes when the content does, so the title animates in again. */
  state: string;
}) {
  const { frame, wall } = usePinnedSky<HTMLElement>([state]);
  return (
    <div className={s.page}>
      <EntryNav />
      <section className={`${s.band} ${children ? s.bandTall : ''}`} ref={frame}>
        <SkyWall className={s.wall} wallRef={wall} />
        <h1 className={`${s.title} ${s.in}`} key={state}>{title}</h1>
        <div className={`${s.lead} ${s.in2}`}>{lead}</div>
      </section>
      {children && <div className={`${s.edge} ${s.edgeTall} ${s.in3}`}>{children}</div>}
      <Legal />
    </div>
  );
}
