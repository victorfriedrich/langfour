'use client';

import { useEffect } from 'react';
import type { ReactNode, RefObject } from 'react';
import { motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';

/** Calls `close` on a click outside `ref` or on Escape while `open`. */
export function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) close(); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') close(); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', escape); };
  }, [ref, open, close]);
}

/** The dropdown itself; `className` places it. Render inside AnimatePresence. */
export function MenuPanel({ className = '', children }: { className?: string; children: ReactNode }) {
  return (
    <motion.div
      role="menu" initial={{ opacity: 0, scale: 0.95, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.95, y: -4 }}
      transition={{ duration: 0.12 }}
      className={`absolute z-30 origin-top-right rounded-lg border border-gray-200 bg-white p-1 shadow-lg shadow-gray-900/5 ${className}`}
    >
      {children}
    </motion.div>
  );
}

export function MenuButton({ icon: Icon, onClick, danger = false, children }: { icon?: LucideIcon; onClick: () => void; danger?: boolean; children: ReactNode }) {
  return (
    <button role="menuitem" onClick={onClick} className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm ${danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-100'}`}>
      {Icon && <Icon size={15} className={`shrink-0 ${danger ? '' : 'text-gray-400'}`}/>}
      {children}
    </button>
  );
}
