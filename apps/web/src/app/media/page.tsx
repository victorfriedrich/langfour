'use client';

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronRight, Clapperboard, FileText, Music, Plus, Puzzle } from 'lucide-react';
import EmptyState from '../components/EmptyState';
import ProtectedRoute from '../components/ProtectedRoute';
import { UserContext } from '@/context/UserContext';
import { useExtensionStatus } from '../hooks/useExtensionStatus';
import type { ExtensionStatus } from '../hooks/useExtensionStatus';
import { ImportedMediaSummary, getLibrary, saveLayout } from './api';
import ImportDialog from './ImportDialog';
import LibraryTree from './LibraryTree';
import { MenuButton, MenuPanel, useDismiss } from './menu';
import { LayoutNode, addFolder, newFolderId, reconcile } from './tree';

// The same two buttons as the Practice page (TodayCard).
const primary = 'inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700';
const secondary = 'inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50';

// Rearranging saves the whole tree once the user pauses.
const SAVE_DELAY_MS = 400;

function MediaPageContent() {
  const { language, fetchWithAuth } = useContext(UserContext);
  const languageCode = language?.code || 'es';
  const [media, setMedia] = useState<ImportedMediaSummary[]>([]);
  const [tree, setTree] = useState<LayoutNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const extension = useExtensionStatus().state;
  const byId = useMemo(() => new Map(media.map((item) => [item.id, item])), [media]);

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const library = await getLibrary(fetchWithAuth, languageCode);
      setMedia(library.media);
      setTree(reconcile(library.layout, library.media.map((item) => item.id)));
    }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to load imported media'); }
    finally { setLoading(false); }
  }, [fetchWithAuth, languageCode]);

  useEffect(() => { refresh(); }, [refresh]);

  const pending = useRef<{ timer: ReturnType<typeof setTimeout>; save: () => void } | null>(null);
  const change = useCallback((next: LayoutNode[]) => {
    setTree(next);
    if (pending.current) clearTimeout(pending.current.timer);
    const save = () => {
      pending.current = null;
      saveLayout(fetchWithAuth, languageCode, next).then(() => setError(''), (err) => setError(err instanceof Error ? err.message : 'Unable to save your folders'));
    };
    pending.current = { timer: setTimeout(save, SAVE_DELAY_MS), save };
  }, [fetchWithAuth, languageCode]);
  // Leaving the page right after a drag still saves it.
  useEffect(() => () => {
    if (!pending.current) return;
    clearTimeout(pending.current.timer);
    pending.current.save();
  }, [languageCode]);

  const createFolder = () => {
    const id = newFolderId();
    change(addFolder(tree, { type: 'folder', id, name: 'New folder', color: 'gray', open: true, children: [] }));
    setRenaming(id);
  };

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-8">
        <header className="mb-8 flex min-h-9 flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold text-gray-900">Media</h1>
          {media.length > 0 && (
            <div className="flex gap-2">
              <button onClick={createFolder} className={secondary}>New folder</button>
              <AddMenu extension={extension} onImport={() => setShowImport(true)}/>
            </div>
          )}
        </header>

        {error && <p className="mb-6 text-sm text-red-600">{error}</p>}
        {loading ? (
          <div className="border-b border-gray-100" aria-label="Loading">
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="flex h-14 items-center gap-3 border-t border-gray-100">
                <span className="h-8 w-8 animate-pulse rounded-lg bg-gray-100" />
                <span className="space-y-1.5">
                  <span className="block h-3 w-56 animate-pulse rounded bg-gray-100" />
                  <span className="block h-3 w-32 animate-pulse rounded bg-gray-100" />
                </span>
              </div>
            ))}
          </div>
        ) : media.length === 0 ? (
          !error && (
            <EmptyState icon={Clapperboard} title="Nothing in your library yet" actions={extension === 'checking' ? null : <>
              <button onClick={() => setShowImport(true)} className={extension === 'missing' ? secondary : primary}><Plus size={16}/>Import episode</button>
              {extension === 'missing' && <Link href="/extension" className={primary}><Puzzle size={16}/>Get the extension</Link>}
            </>}>
              {extension === 'missing' ? 'Add articles and songs as you browse with the Chrome extension, or import an episode transcript.'
                : extension === 'installed' ? <AddFromReader className="mt-1 justify-center"/> : null}
            </EmptyState>
          )
        ) : (
          <LibraryTree tree={tree} media={byId} onChange={change} renaming={renaming} onRename={setRenaming}/>
        )}
      </div>

      {showImport && <ImportDialog language={languageCode} existing={media} onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); refresh(); }}/>}
    </div>
  );
}

// Both ways into the Library: an episode transcript imported here, and
// articles and songs added from the extension's reader.
function AddMenu({ extension, onImport }: { extension: ExtensionStatus['state']; onImport: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(ref, open, close);
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu" className={primary}>
        Add<ChevronDown size={14} className="-mr-0.5"/>
      </button>
      <AnimatePresence>
        {open && (
          <MenuPanel className="right-0 top-full mt-1.5 w-72">
            <MenuButton icon={FileText} onClick={() => { close(); onImport(); }}>Episode transcript…</MenuButton>
            <div className="my-1 h-px bg-gray-100"/>
            <div className="px-2.5 pb-2 pt-1.5">
              <p className="flex items-center gap-2 text-sm text-gray-700"><Music size={15} className="text-gray-400"/>Article or song</p>
              {extension === 'missing'
                ? <Link href="/extension" onClick={close} className="ml-[23px] mt-1 inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-700">Get the extension<ChevronRight size={14}/></Link>
                : <AddFromReader lead={false} className="ml-[23px] mt-1.5"/>}
            </div>
          </MenuPanel>
        )}
      </AnimatePresence>
    </div>
  );
}

// How articles and songs get here once the extension is installed: the
// reader's shortcut, then its Add to Library button. iPhone and iPad have no
// shortcut (the Safari build drops it), so there the popup's button opens the
// reader. iPads that report a Mac user agent are told apart by touch. Only
// rendered after the extension has answered, so reading navigator here
// cannot break hydration.
function AddFromReader({ className = '', lead = true }: { className?: string; lead?: boolean }) {
  const touch = navigator.maxTouchPoints > 1;
  const mac = /Mac/.test(navigator.userAgent);
  const key = 'inline-grid h-6 min-w-6 place-items-center rounded-md border border-gray-200 bg-white px-1.5 font-sans text-xs font-medium text-gray-700 shadow-[0_1px_0_rgb(0_0_0/0.04)]';
  const keys = mac ? ['⌘', '⇧', 'Y'] : ['Ctrl', 'Shift', 'Y'];
  const steps = touch
    ? [<span key="ext">Langfour Reader</span>, <span key="read">Read this page</span>]
    : [<span key="keys" className="inline-flex items-center gap-1" aria-label={`Press ${keys.join(' ')}`}>{keys.map((k) => <kbd key={k} className={key}>{k}</kbd>)}</span>];
  return (
    <div className={`flex flex-wrap items-center gap-x-2.5 gap-y-2 text-sm text-gray-500 ${className}`}>
      {lead && <span>Any article or song</span>}
      {[...steps, <span key="add" className="font-medium text-gray-700">Add to Library</span>].map((step, i) => (
        <span key={step.key} className="inline-flex items-center gap-2.5">
          {(lead || i > 0) && <ChevronRight size={14} className="text-gray-300" aria-hidden/>}
          {step}
        </span>
      ))}
    </div>
  );
}

export default function MediaPage() { return <ProtectedRoute><MediaPageContent/></ProtectedRoute>; }
