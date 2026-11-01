'use client';

import { useEffect, useRef, useState } from 'react';
import type { DragEvent, ReactNode } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';
import { ArrowDown, ArrowUp, Check, ChevronRight, CornerLeftUp, FileText, Film, Folder, FolderInput, FolderOpen, FolderPlus, GripVertical, MoreHorizontal, Music, Newspaper, Pencil, Trash2, Tv } from 'lucide-react';
import type { ImportedMediaSummary, MediaKind } from './api';
import {
  FOLDER_COLORS, MAX_FOLDER_DEPTH, addFolder, contains, countItems, findNode, keyOf, listFolders, moveNode, moveToRoot, newFolderId, removeFolder, shift, updateFolder,
} from './tree';
import type { DropPosition, FolderColor, FolderNode, LayoutNode } from './tree';

// Each kind of item gets its own tint, and each folder the colour its owner
// picked, so a long Library can be scanned by colour. Full class names, so
// Tailwind keeps them.
const KIND: Record<MediaKind, { icon: LucideIcon; label: string; tile: string }> = {
  series: { icon: Tv, label: 'Episode', tile: 'bg-violet-50 text-violet-500' },
  movie: { icon: Film, label: 'Movie', tile: 'bg-amber-50 text-amber-500' },
  article: { icon: Newspaper, label: 'Article', tile: 'bg-sky-50 text-sky-500' },
  song: { icon: Music, label: 'Song', tile: 'bg-rose-50 text-rose-500' },
  text: { icon: FileText, label: 'Text', tile: 'bg-gray-100 text-gray-500' },
};
export const FOLDER_TONE: Record<FolderColor, { icon: string; swatch: string }> = {
  indigo: { icon: 'text-indigo-500 fill-indigo-100', swatch: 'bg-indigo-400' },
  sky: { icon: 'text-sky-500 fill-sky-100', swatch: 'bg-sky-400' },
  emerald: { icon: 'text-emerald-500 fill-emerald-100', swatch: 'bg-emerald-400' },
  amber: { icon: 'text-amber-500 fill-amber-100', swatch: 'bg-amber-400' },
  rose: { icon: 'text-rose-500 fill-rose-100', swatch: 'bg-rose-400' },
  violet: { icon: 'text-violet-500 fill-violet-100', swatch: 'bg-violet-400' },
  gray: { icon: 'text-gray-400 fill-gray-100', swatch: 'bg-gray-400' },
};

const formatDuration = (seconds: number) => {
  const minutes = Math.round(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes} min`;
};

const timeToFinish = (media: ImportedMediaSummary) =>
  media.duration ? formatDuration(media.duration) : media.wordCount ? `${Math.max(1, Math.round(media.wordCount / 200))} min read` : null;

const hostOf = (url: string | null | undefined) => {
  try { return url ? new URL(url).hostname.replace(/^www\./, '') : null; } catch { return null; }
};

// What each row shows after the title: who or where it is from, then the
// episode number for series. The title itself is always the item's own.
const detailsOf = (media: ImportedMediaSummary) => {
  const parts = media.type === 'series'
    ? [media.series, media.season === null || media.episode === null ? null : `S${String(media.season).padStart(2, '0')} E${String(media.episode).padStart(2, '0')}`]
    : media.type === 'article' ? [media.site || hostOf(media.sourceUrl)]
      : media.type === 'song' ? [media.artist] : [];
  return [...parts, timeToFinish(media)].filter(Boolean).join(' · ');
};

const spring = { type: 'spring', stiffness: 520, damping: 38 } as const;

interface TreeProps {
  tree: LayoutNode[];
  media: Map<string, ImportedMediaSummary>;
  onChange: (tree: LayoutNode[]) => void;
  renaming: string | null;
  onRename: (folderId: string | null) => void;
}

type Drop = { key: string; position: DropPosition } | { key: 'end'; position: 'after' };

export default function LibraryTree({ tree, media, onChange, renaming, onRename }: TreeProps) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [drop, setDrop] = useState<Drop | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  // The row that just moved glows for a moment, so the eye can follow it.
  const [moved, setMoved] = useState<string | null>(null);
  useEffect(() => {
    if (!moved) return;
    const timer = setTimeout(() => setMoved(null), 900);
    return () => clearTimeout(timer);
  }, [moved]);

  const commit = (next: LayoutNode[], key?: string) => {
    if (next === tree) return;
    onChange(next);
    if (key) setMoved(key);
  };

  const endDrag = () => { setDragging(null); setDrop(null); };

  const dragProps = (node: LayoutNode) => {
    const key = keyOf(node);
    return {
      draggable: renaming !== node.id,
      onDragStart: (event: DragEvent) => {
        event.dataTransfer.setData('text/plain', key);
        event.dataTransfer.effectAllowed = 'move';
        setMenu(null);
        // Restyling the row inside dragstart can cancel the drag in Chrome.
        setTimeout(() => setDragging(key));
      },
      onDragEnd: endDrag,
      onDragOver: (event: DragEvent<HTMLElement>) => {
        if (!dragging || dragging === key) return;
        const moving = findNode(tree, dragging);
        if (!moving || (moving.type === 'folder' && contains(moving, key))) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const y = (event.clientY - rect.top) / rect.height;
        // A folder takes a drop on most of its row; an open one's lower edge
        // sits on its first child, so dropping there puts the item inside too.
        const position: DropPosition = node.type === 'folder'
          ? (y < 0.3 ? 'before' : !node.open && y > 0.75 ? 'after' : 'inside')
          : (y < 0.5 ? 'before' : 'after');
        if (moveNode(tree, dragging, key, position) === tree) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        if (drop?.key !== key || drop.position !== position) setDrop({ key, position });
      },
      onDrop: (event: DragEvent) => {
        event.preventDefault();
        if (dragging && drop?.key === key) commit(moveNode(tree, dragging, key, drop.position), dragging);
        endDrag();
      },
    };
  };

  const ctx: LevelContext = { tree, media, commit, renaming, onRename, dragging, drop, setDrop, menu, setMenu, moved, dragProps };

  return (
    <div onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDrop(null); }}>
      <Level nodes={tree} depth={0} ctx={ctx}/>
      <AnimatePresence>
        {dragging && (
          <motion.div
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            onDragOver={(event) => { event.preventDefault(); if (drop?.key !== 'end') setDrop({ key: 'end', position: 'after' }); }}
            onDrop={(event) => { event.preventDefault(); commit(moveToRoot(tree, dragging, 'end'), dragging); endDrag(); }}
          >
            <div className={`mt-2 flex h-10 items-center justify-center rounded-lg border-2 border-dashed text-sm transition-colors ${drop?.key === 'end' ? 'border-indigo-300 bg-indigo-50 text-indigo-600' : 'border-gray-200 text-gray-400'}`}>
              Move to the end
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface LevelContext {
  tree: LayoutNode[];
  media: Map<string, ImportedMediaSummary>;
  commit: (next: LayoutNode[], key?: string) => void;
  renaming: string | null;
  onRename: (folderId: string | null) => void;
  dragging: string | null;
  drop: Drop | null;
  setDrop: (drop: Drop | null) => void;
  menu: string | null;
  setMenu: (key: string | null) => void;
  moved: string | null;
  dragProps: (node: LayoutNode) => Record<string, unknown>;
}

function Level({ nodes, depth, ctx }: { nodes: LayoutNode[]; depth: number; ctx: LevelContext }) {
  return (
    <ul>
      {nodes.map((node) => (
        <motion.li key={keyOf(node)} layout="position" transition={spring}>
          {node.type === 'folder'
            ? <FolderRow folder={node} depth={depth} ctx={ctx}/>
            : ctx.media.has(node.id) && <ItemRow item={ctx.media.get(node.id)!} nodeKey={keyOf(node)} ctx={ctx}/>}
        </motion.li>
      ))}
    </ul>
  );
}

// The shared shell of a row: drop line above or below, the glow after a
// move, and a grip in the gutter on hover.
function RowShell({ nodeKey, node, ctx, children }: { nodeKey: string; node: LayoutNode; ctx: LevelContext; children: ReactNode }) {
  const target = ctx.drop?.key === nodeKey ? ctx.drop.position : null;
  return (
    <div
      {...ctx.dragProps(node)}
      className={`group relative flex min-h-11 items-center gap-2 rounded-lg py-1.5 pl-1 pr-1 transition-colors ${
        ctx.dragging === nodeKey ? 'opacity-40' : ''} ${
        target === 'inside' ? 'bg-indigo-50 ring-1 ring-inset ring-indigo-200' : ctx.moved === nodeKey ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}
    >
      <GripVertical size={14} aria-hidden className="absolute -left-5 hidden cursor-grab text-gray-300 opacity-0 group-hover:opacity-100 sm:block"/>
      {(target === 'before' || target === 'after') && (
        <span aria-hidden className={`pointer-events-none absolute left-6 right-0 z-10 h-0.5 rounded-full bg-indigo-500 ${target === 'before' ? '-top-px' : '-bottom-px'}`}>
          <span className="absolute -left-1.5 -top-[3px] h-2 w-2 rounded-full border-2 border-indigo-500 bg-white"/>
        </span>
      )}
      {children}
    </div>
  );
}

function FolderRow({ folder, depth, ctx }: { folder: FolderNode; depth: number; ctx: LevelContext }) {
  const key = keyOf(folder);
  const Icon = folder.open ? FolderOpen : Folder;
  const target = ctx.drop?.key === key && ctx.drop.position === 'inside';
  const count = countItems(folder);
  const toggle = () => ctx.commit(updateFolder(ctx.tree, folder.id, { open: !folder.open }));
  return (
    <>
      <RowShell nodeKey={key} node={folder} ctx={ctx}>
        <button onClick={toggle} aria-label={folder.open ? `Close ${folder.name}` : `Open ${folder.name}`} className="grid h-5 w-5 shrink-0 place-items-center rounded text-gray-400 hover:bg-gray-200/70 hover:text-gray-600">
          <ChevronRight size={14} className={`transition-transform duration-200 ${folder.open ? 'rotate-90' : ''}`}/>
        </button>
        <span className="grid h-7 w-7 shrink-0 place-items-center">
          <Icon size={19} strokeWidth={1.75} className={`${FOLDER_TONE[folder.color].icon} transition-transform duration-200 ${target ? '-rotate-6 scale-125' : ''}`}/>
        </span>
        {ctx.renaming === folder.id ? (
          <RenameInput folder={folder} ctx={ctx}/>
        ) : (
          <button onClick={toggle} onDoubleClick={() => ctx.onRename(folder.id)} aria-expanded={folder.open} className="flex min-w-0 flex-1 items-center gap-2 text-left">
            <span className="truncate text-sm font-medium text-gray-900">{folder.name}</span>
            <span className="shrink-0 rounded-full bg-gray-100 px-1.5 text-xs font-medium tabular-nums leading-5 text-gray-500">{count}</span>
          </button>
        )}
        <RowMenu nodeKey={key} label={folder.name} ctx={ctx}>
          {(close) => (
            <>
              <MenuButton icon={Pencil} onClick={() => { close(); ctx.onRename(folder.id); }}>Rename</MenuButton>
              {depth + 1 < MAX_FOLDER_DEPTH && (
                <MenuButton icon={FolderPlus} onClick={() => {
                  close();
                  const id = newFolderId();
                  ctx.commit(addFolder(ctx.tree, { type: 'folder', id, name: 'New folder', color: folder.color, open: true, children: [] }, folder.id));
                  ctx.onRename(id);
                }}>New folder inside</MenuButton>
              )}
              <div className="flex items-center gap-1.5 px-2.5 py-2" role="group" aria-label="Folder colour">
                {FOLDER_COLORS.map((color) => (
                  <button key={color} aria-label={`Colour ${color}`} aria-pressed={folder.color === color}
                    onClick={() => ctx.commit(updateFolder(ctx.tree, folder.id, { color }))}
                    className={`grid h-5 w-5 place-items-center rounded-full ${FOLDER_TONE[color].swatch} transition-transform hover:scale-110 ${folder.color === color ? 'ring-2 ring-gray-900/20 ring-offset-1' : ''}`}>
                    {folder.color === color && <Check size={11} strokeWidth={3} className="text-white"/>}
                  </button>
                ))}
              </div>
              <MoveActions nodeKey={key} ctx={ctx} close={close}/>
              <div className="my-1 h-px bg-gray-100"/>
              <MenuButton icon={Trash2} danger onClick={() => { close(); ctx.commit(removeFolder(ctx.tree, folder.id)); }}>
                Delete folder<span className="ml-auto text-xs text-gray-400">keeps items</span>
              </MenuButton>
            </>
          )}
        </RowMenu>
      </RowShell>
      <AnimatePresence initial={false}>
        {folder.open && (
          <motion.div
            initial={{ height: 0, opacity: 0, overflow: 'hidden' }}
            animate={{ height: 'auto', opacity: 1, transitionEnd: { overflow: 'visible' } }}
            exit={{ height: 0, opacity: 0, overflow: 'hidden' }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {/* The guide line sits under the chevron, as in an outliner. */}
            <div className="ml-[13px] border-l border-gray-200/80 pl-2">
              {folder.children.length > 0 ? <Level nodes={folder.children} depth={depth + 1} ctx={ctx}/> : (
                <div
                  onDragOver={(event) => { if (ctx.dragging && moveNode(ctx.tree, ctx.dragging, key, 'inside') !== ctx.tree) { event.preventDefault(); if (!target) ctx.setDrop({ key, position: 'inside' }); } }}
                  onDrop={(event) => { event.preventDefault(); if (ctx.dragging) ctx.commit(moveNode(ctx.tree, ctx.dragging, key, 'inside'), ctx.dragging); ctx.setDrop(null); }}
                  className={`my-1 flex h-9 items-center rounded-lg border border-dashed pl-3 text-sm transition-colors ${target ? 'border-indigo-300 text-indigo-500' : 'border-gray-200 text-gray-400'}`}
                >
                  Empty. Drag things in here.
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

function ItemRow({ item, nodeKey, ctx }: { item: ImportedMediaSummary; nodeKey: string; ctx: LevelContext }) {
  const { icon: Icon, label, tile } = KIND[item.type] ?? KIND.text;
  const details = detailsOf(item);
  return (
    <RowShell nodeKey={nodeKey} node={{ type: 'item', id: item.id }} ctx={ctx}>
      <span className="w-5 shrink-0"/>
      <Link href={`/media/${encodeURIComponent(item.id)}`} draggable={false} aria-label={`Open vocabulary for ${item.title}`} className="flex min-w-0 flex-1 items-center gap-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300">
        <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg ${tile}`} aria-label={label}>
          <Icon size={15} strokeWidth={2}/>
        </span>
        <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-baseline sm:gap-2">
          <span className="truncate text-sm text-gray-900">{item.title}</span>
          {details && <span className="truncate text-sm text-gray-400">{details}</span>}
        </span>
        <span className="hidden shrink-0 pl-2 text-sm tabular-nums text-gray-400 sm:block">{new Date(item.importedAt).toLocaleDateString()}</span>
      </Link>
      <RowMenu nodeKey={nodeKey} label={item.title} ctx={ctx}>
        {(close) => <MoveActions nodeKey={nodeKey} ctx={ctx} close={close}/>}
      </RowMenu>
    </RowShell>
  );
}

function RenameInput({ folder, ctx }: { folder: FolderNode; ctx: LevelContext }) {
  const done = useRef(false);
  const finish = (value: string | null) => {
    if (done.current) return;
    done.current = true;
    const name = value?.trim().slice(0, 80);
    if (name && name !== folder.name) ctx.commit(updateFolder(ctx.tree, folder.id, { name }));
    ctx.onRename(null);
  };
  return (
    <input
      autoFocus defaultValue={folder.name} aria-label="Folder name" maxLength={80}
      onFocus={(event) => event.currentTarget.select()}
      onBlur={(event) => finish(event.currentTarget.value)}
      onKeyDown={(event) => {
        if (event.key === 'Enter') finish(event.currentTarget.value);
        if (event.key === 'Escape') finish(null);
      }}
      className="min-w-0 flex-1 rounded-md border border-indigo-300 bg-white px-2 py-1 text-sm font-medium text-gray-900 outline-none ring-2 ring-indigo-100"
    />
  );
}

// Up, down and into a folder: the way to rearrange without dragging, on a
// phone or from the keyboard.
function MoveActions({ nodeKey, ctx, close }: { nodeKey: string; ctx: LevelContext; close: () => void }) {
  const moving = findNode(ctx.tree, nodeKey);
  if (!moving) return null;
  const run = (next: LayoutNode[]) => { close(); ctx.commit(next, nodeKey); };
  const targets = listFolders(ctx.tree).filter(({ folder }) => !(moving.type === 'folder' && contains(moving, keyOf(folder)))
    && moveNode(ctx.tree, nodeKey, keyOf(folder), 'inside') !== ctx.tree);
  const atRoot = ctx.tree.some((node) => keyOf(node) === nodeKey);
  return (
    <>
      <MenuButton icon={ArrowUp} onClick={() => run(shift(ctx.tree, nodeKey, -1))}>Move up</MenuButton>
      <MenuButton icon={ArrowDown} onClick={() => run(shift(ctx.tree, nodeKey, 1))}>Move down</MenuButton>
      {(targets.length > 0 || !atRoot) && (
        <>
          <div className="my-1 h-px bg-gray-100"/>
          <p className="flex items-center gap-2 px-2.5 pb-1 pt-1.5 text-xs font-medium text-gray-400"><FolderInput size={13}/>Move to</p>
          <div className="max-h-48 overflow-y-auto">
            {!atRoot && <MenuButton icon={CornerLeftUp} onClick={() => run(moveToRoot(ctx.tree, nodeKey, 'start'))}>Top level</MenuButton>}
            {targets.map(({ folder, depth }) => (
              <button key={folder.id} onClick={() => run(moveNode(ctx.tree, nodeKey, keyOf(folder), 'inside'))}
                className="flex w-full items-center gap-2 rounded-md py-1.5 pr-2.5 text-left text-sm text-gray-700 hover:bg-gray-100" style={{ paddingLeft: 10 + depth * 14 }}>
                <Folder size={15} strokeWidth={1.75} className={`shrink-0 ${FOLDER_TONE[folder.color].icon}`}/>
                <span className="truncate">{folder.name}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </>
  );
}

function RowMenu({ nodeKey, label, ctx, children }: { nodeKey: string; label: string; ctx: LevelContext; children: (close: () => void) => ReactNode }) {
  const open = ctx.menu === nodeKey;
  const ref = useRef<HTMLDivElement>(null);
  const { setMenu } = ctx;
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => { if (!ref.current?.contains(event.target as Node)) setMenu(null); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setMenu(null); };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', escape); };
  }, [open, setMenu]);
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setMenu(open ? null : nodeKey)} aria-label={`Actions for ${label}`} aria-expanded={open}
        className={`grid h-7 w-7 place-items-center rounded-md text-gray-400 hover:bg-gray-200/70 hover:text-gray-700 group-hover:opacity-100 [@media(hover:none)]:opacity-100 ${open ? 'bg-gray-200/70 opacity-100' : 'opacity-0 focus-visible:opacity-100'}`}
      >
        <MoreHorizontal size={16}/>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu" initial={{ opacity: 0, scale: 0.95, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.95, y: -4 }}
            transition={{ duration: 0.12 }}
            className="absolute right-0 top-8 z-30 w-60 origin-top-right rounded-xl border border-gray-200 bg-white p-1 shadow-lg shadow-gray-900/5"
          >
            {children(() => setMenu(null))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function MenuButton({ icon: Icon, onClick, danger = false, children }: { icon: LucideIcon; onClick: () => void; danger?: boolean; children: ReactNode }) {
  return (
    <button role="menuitem" onClick={onClick} className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm ${danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-100'}`}>
      <Icon size={15} className={`shrink-0 ${danger ? '' : 'text-gray-400'}`}/>
      {children}
    </button>
  );
}
