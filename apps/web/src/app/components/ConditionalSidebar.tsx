'use client';
import React from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from '@/app/components/Sidebar';

// Pages without the sidebar, and so without its fixed mobile header.
const NO_SIDEBAR = ['/get-started', '/start-learning', '/login', '/privacy', '/oauth/'];

export function showsSidebar(pathname: string): boolean {
  return !NO_SIDEBAR.some((prefix) => pathname.startsWith(prefix));
}

export default function ConditionalSidebar() {
  const pathname = usePathname();
  return showsSidebar(pathname) ? <Sidebar /> : null;
}

// Below md the sidebar's header is fixed over the top 3rem; leave room for it
// only where it's shown, or pages without it start below an empty band.
// main is the scroll container: min-h-0 keeps it at the body's height in the
// mobile column layout. Otherwise it grows to its content and the document
// scrolls instead, sliding the page under the fixed header.
export function AppMain({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <main className={`flex-1 min-h-0 md:pt-0 ${showsSidebar(pathname) ? 'pt-12' : ''} overflow-y-auto h-dvh`}>
      {children}
    </main>
  );
}
