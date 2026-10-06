'use client';
import { usePathname } from 'next/navigation';
import Sidebar from '@/app/components/Sidebar';

export default function ConditionalSidebar() {
  const pathname = usePathname();

  // Hide sidebar on get‑started pages
  if (pathname.startsWith('/get-started') || pathname.startsWith('/start-learning') || pathname.startsWith('/login') || pathname.startsWith('/privacy')) {
    return null;
  }

  return <Sidebar />;
}
