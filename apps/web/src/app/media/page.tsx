'use client';

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { ChevronRight, Clapperboard, FolderPlus, Plus, Puzzle } from 'lucide-react';
import EmptyState from '../components/EmptyState';
import ProtectedRoute from '../components/ProtectedRoute';
import { UserContext } from '@/context/UserContext';
import { useExtensionStatus } from '../hooks/useExtensionStatus';
import { ImportedMediaSummary, getLibrary, saveLayout } from './api';
import ImportDialog from './ImportDialog';
import LibraryTree from './LibraryTree';
import { FOLDER_COLORS, LayoutNode, addFolder, listFolders, newFolderId, reconcile } from './tree';

// The same two buttons as the Practice page.
const primary = 'inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700';
const secondary = 'inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50';

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
    // Each new folder takes the next colour, so a few in a row look distinct.
    const color = FOLDER_COLORS[listFolders(tree).length % (FOLDER_COLORS.length - 1)];
    change(addFolder(tree, { type: 'folder', id, name: 'New folder', color, open: true, children: [] }));
    setRenaming(id);
  };

  return (
    <div className="min-h-screen bg-white">
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-8">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-4 sm:flex-nowrap">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold text-gray-900">Media</h1>
            <p className="mt-1 text-sm text-gray-500">Learn the words of an episode, article or song before you start.</p>
          </div>
          {media.length > 0 && (
            <div className="flex flex-wrap gap-3 sm:shrink-0">
              <button onClick={createFolder} className={secondary}><FolderPlus size={16}/>New folder</button>
              <button onClick={() => setShowImport(true)} className={secondary}><Plus size={16}/>Import episode</button>
              {extension === 'missing' && <Link href="/extension" className={primary}><Puzzle size={16}/>Get the extension</Link>}
            </div>
          )}
        </header>

        {error && <p className="mb-6 text-sm text-red-600">{error}</p>}
        {loading ? (
          <div className="space-y-1" aria-label="Loading">
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="flex h-11 items-center gap-2 pl-7">
                <span className="h-7 w-7 animate-pulse rounded-lg bg-gray-100" />
                <span className="h-3 w-56 animate-pulse rounded bg-gray-100" />
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
          <>
            <LibraryTree tree={tree} media={byId} onChange={change} renaming={renaming} onRename={setRenaming}/>
            {extension === 'installed' && <AddFromReader className="mt-6 pl-1"/>}
          </>
        )}
      </div>

      {showImport && <ImportDialog language={languageCode} existing={media} onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); refresh(); }}/>}
    </div>
  );
}

// How articles and songs get here once the extension is installed: the
// reader's shortcut, then its Add to Library button. iPhone and iPad have no
// shortcut (the Safari build drops it), so there the popup's button opens the
// reader. iPads that report a Mac user agent are told apart by touch. Only
// rendered after the extension has answered, so reading navigator here
// cannot break hydration.
function AddFromReader({ className = '' }: { className?: string }) {
  const touch = navigator.maxTouchPoints > 1;
  const mac = /Mac/.test(navigator.userAgent);
  const key = 'inline-grid h-6 min-w-6 place-items-center rounded-md border border-gray-200 bg-white px-1.5 font-sans text-xs font-medium text-gray-700 shadow-[0_1px_0_rgb(0_0_0/0.04)]';
  const keys = mac ? ['⌘', '⇧', 'Y'] : ['Ctrl', 'Shift', 'Y'];
  const steps = touch
    ? [<span key="ext">Langfour Reader</span>, <span key="read">Read this page</span>]
    : [<span key="keys" className="inline-flex items-center gap-1" aria-label={`Press ${keys.join(' ')}`}>{keys.map((k) => <kbd key={k} className={key}>{k}</kbd>)}</span>];
  return (
    <div className={`flex flex-wrap items-center gap-x-2.5 gap-y-2 text-sm text-gray-500 ${className}`}>
      <span>Any article or song</span>
      {[...steps, <span key="add" className="font-medium text-gray-700">Add to Library</span>].map((step) => (
        <span key={step.key} className="inline-flex items-center gap-2.5">
          <ChevronRight size={14} className="text-gray-300" aria-hidden/>
          {step}
        </span>
      ))}
    </div>
  );
}

export default function MediaPage() { return <ProtectedRoute><MediaPageContent/></ProtectedRoute>; }
