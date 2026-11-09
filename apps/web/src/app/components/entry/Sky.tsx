'use client';

import { useLayoutEffect, useRef, type RefObject } from 'react';

/** The landing page's sky: pale blue with soft white clouds. */
export function SkyWall({ className, wallRef }: { className?: string; wallRef?: RefObject<SVGSVGElement> }) {
  return (
    <svg ref={wallRef} className={className} viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <filter id="lf-sky-blur" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="46" />
        </filter>
      </defs>
      <rect width="1600" height="1000" fill="#BFDAF8" />
      <g filter="url(#lf-sky-blur)" fill="#fff">
        <ellipse cx="220" cy="160" rx="330" ry="90" opacity=".85" />
        <ellipse cx="520" cy="96" rx="210" ry="56" opacity=".6" />
        <ellipse cx="1320" cy="210" rx="380" ry="110" opacity=".9" />
        <ellipse cx="90" cy="520" rx="300" ry="120" opacity=".7" />
        <ellipse cx="1520" cy="600" rx="300" ry="140" opacity=".75" />
        <ellipse cx="800" cy="420" rx="520" ry="130" opacity=".42" />
      </g>
    </svg>
  );
}

/** Pin the sky to the viewport rather than to its frame. The band on the
 *  language step and the panel beside the level step then show the same
 *  clouds in the same places, so one can glide into the other without the
 *  sky moving. */
export function pinToViewport(frame: HTMLElement | null, wall: SVGSVGElement | null) {
  if (!frame || !wall) return;
  const r = frame.getBoundingClientRect();
  wall.style.inset = 'auto';
  wall.style.left = `${-r.left}px`;
  wall.style.top = `${-r.top}px`;
  wall.style.width = `${document.documentElement.clientWidth}px`;
  wall.style.height = `${window.innerHeight}px`;
}

export function usePinnedSky<T extends HTMLElement>(deps: unknown[] = []) {
  const frame = useRef<T>(null);
  const wall = useRef<SVGSVGElement>(null);
  useLayoutEffect(() => {
    const pin = () => pinToViewport(frame.current, wall.current);
    pin();
    window.addEventListener('resize', pin);
    return () => window.removeEventListener('resize', pin);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { frame, wall };
}
