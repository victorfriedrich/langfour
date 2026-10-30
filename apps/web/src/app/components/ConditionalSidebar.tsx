'use client';
import { usePathname } from 'next/navigation';
import Sidebar from '@/app/components/Sidebar';

// Pages without the sidebar, and so without its mobile header.
const NO_SIDEBAR = ['/get-started', '/start-learning', '/login', '/privacy', '/oauth/'];

function showsSidebar(pathname: string): boolean {
  return !NO_SIDEBAR.some((prefix) => pathname.startsWith(prefix));
}

export default function ConditionalSidebar() {
  const pathname = usePathname();
  return showsSidebar(pathname) ? <Sidebar /> : null;
}
