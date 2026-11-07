'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { AnimatePresence } from 'framer-motion';
import { DndContext, MouseSensor, TouchSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core';
import type { DragEndEvent, DragMoveEvent } from '@dnd-kit/core';
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import type { SortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { LucideIcon } from 'lucide-react';
import { FileText, Film, Folder, FolderOpen, GripVertical, MoreHorizontal, Music, Newspaper, Tv } from 'lucide-react';
import type { ImportedMediaSummary, MediaKind } from './api';
import { MenuButton, MenuPanel, useDismiss } from './menu';
import {
  MAX_FOLDER_DEPTH, addFolder, contains, countItems, drop, findNode, flatten, keyOf, listFolders, moveNode, moveToRoot, newFolderId, parentOf, project, removeFolder, shift, updateFolder,
} from './tree';
import type { FlatRow, FolderNode, LayoutNode } from './tree';

// Each kind of item gets its own tint, so a long Library can be scanned by
// kind; folders all share the app's indigo. Full class names, so Tailwind
// keeps them.
const KIND: Record<MediaKind, { icon: LucideIcon; label: string; tile: string }> = {
  series: { icon: Tv, label: 'Episode', tile: 'bg-violet-50 text-violet-500' },
  movie: { icon: Film, label: 'Movie', tile: 'bg-amber-50 text-amber-500' },
  article: { icon: Newspaper, label: 'Article', tile: 'bg-sky-50 text-sky-500' },
  song: { icon: Music, label: 'Song', tile: 'bg-rose-50 text-rose-500' },
  text: { icon: FileText, label: 'Text', tile: 'bg-gray-100 text-gray-500' },
};
const FOLDER_TILE = 'bg-indigo-50 text-indigo-500';

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

// Rows inside a folder sit one icon further in, and dragging a row this far
// sideways moves it one level in or out.
const INDENT = 44;

// Held over the middle half of a folder's row, a dragged row goes into that
// folder; nearer its top or bottom edge it lands beside it.
const INTO_BAND = 0.25;

interface TreeProps {
  tree: LayoutNode[];
  media: Map<string, ImportedMediaSummary>;
  onChange: (tree: LayoutNode[]) => void;
  renaming: string | null;
  onRename: (folderId: string | null) => void;
}

// Dragging moves the row itself: it lifts out of the list and follows the
// pointer while the other rows make room where it will land. The rows are
// one flat list, each indented by its depth, as in an outliner.
export default function LibraryTree({ tree, media, onChange, renaming, onRename }: TreeProps) {
  const [active, setActive] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [offsetX, setOffsetX] = useState(0);
  // The folder the dragged row is held over, which it drops straight into.
  const [target, setTarget] = useState<string | null>(null);
  const [menu, setMenu] = useState<string | null>(null);
  // The row that just moved glows for a moment, so the eye can follow it.
  const [moved, setMoved] = useState<string | null>(null);
  useEffect(() => {
    if (!moved) return;
    const timer = setTimeout(() => setMoved(null), 900);
    return () => clearTimeout(timer);
  }, [moved]);
  // A drag ends with a click on the row it started on; that click mustn't
  // open the item.
  const dragged = useRef(false);

  const rows = useMemo(
    () => flatten(tree, true, active ?? undefined).filter((row) => row.node.type === 'folder' || media.has(row.node.id)),
    [tree, active, media],
  );
  const targetRow = target ? rows.find((row) => row.key === target) : undefined;
  const landing = !active || !over ? null
    : targetRow ? { depth: targetRow.depth + 1, parent: targetRow.key, after: targetRow.key }
      : project(rows, active, over, offsetX, INDENT);
  // While a folder takes the row, the other rows stay where they are.
  const strategy = useCallback<SortingStrategy>((args) => target ? null : verticalListSortingStrategy(args), [target]);

  // Touch drags start after a short hold, so a swipe still scrolls the page.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 6 } }),
  );

  const commit = (next: LayoutNode[], key?: string) => {
    if (next === tree) return;
    onChange(next);
    if (key) setMoved(key);
  };

  const reset = () => {
    setActive(null); setOver(null); setOffsetX(0); setTarget(null);
    setTimeout(() => { dragged.current = false; });
  };

  // A quick drop can end the drag before the last move has re-rendered, so
  // the folder under it is worked out again from the drop itself.
  const end = (event: DragEndEvent) => {
    const into = targetOf(event) ?? target;
    if (active && into) {
      commit(moveNode(tree, active, into, 'inside'), active);
      reset();
      return;
    }
    const at = rows.findIndex((row) => row.key === active);
    const unchanged = landing && landing.parent === rows[at]?.parent && landing.after === (rows[at - 1]?.key ?? null);
    if (active && landing && !unchanged) commit(drop(tree, active, landing.after, landing.parent), active);
    reset();
  };

  const targetOf = ({ active: moving, over: hovered }: DragMoveEvent | DragEndEvent) =>
    folderUnder(tree, String(moving.id), hovered ? String(hovered.id) : null, moving.rect.current.translated, hovered?.rect ?? null);

  const ctx: RowContext = { tree, media, commit, renaming, onRename, active, into: landing?.parent ?? null, menu, setMenu, moved };

  return (
    <DndContext
      sensors={sensors} collisionDetection={closestCenter}
      onDragStart={({ active: start }) => { dragged.current = true; setMenu(null); setActive(String(start.id)); setOver(String(start.id)); }}
      onDragMove={(event) => { setOffsetX(event.delta.x); setTarget(targetOf(event)); }}
      onDragOver={({ over: hovered }) => setOver(hovered ? String(hovered.id) : null)}
      onDragEnd={end}
      onDragCancel={reset}
    >
      <SortableContext items={rows.map((row) => row.key)} strategy={strategy}>
        <ul className="border-b border-gray-100" onClickCapture={(event) => { if (dragged.current) { event.preventDefault(); event.stopPropagation(); } }}>
          {rows.map((row) => (
            <SortableRow key={row.key} row={row} depth={row.key === active && landing ? landing.depth : row.depth} ctx={ctx}/>
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}

// The folder `over` if the dragged row's middle is held over the middle of
// its row and the row may go in (a folder can't go into itself or too deep).
// Rects are where the rows sit before anything moves aside.
function folderUnder(tree: LayoutNode[], active: string, over: string | null, dragged: { top: number; height: number } | null, rect: { top: number; height: number } | null): string | null {
  if (!over || over === active || !over.startsWith('folder:') || !dragged || !rect) return null;
  const offset = dragged.top + dragged.height / 2 - (rect.top + rect.height / 2);
  if (Math.abs(offset) > rect.height * INTO_BAND) return null;
  return moveNode(tree, active, over, 'inside') === tree ? null : over;
}

interface RowContext {
  tree: LayoutNode[];
  media: Map<string, ImportedMediaSummary>;
  commit: (next: LayoutNode[], key?: string) => void;
  renaming: string | null;
  onRename: (folderId: string | null) => void;
  // The row being dragged, and the folder it would land in.
  active: string | null;
  into: string | null;
  menu: string | null;
  setMenu: (key: string | null) => void;
  moved: string | null;
}

function SortableRow({ row, depth, ctx }: { row: FlatRow; depth: number; ctx: RowContext }) {
  const { setNodeRef, listeners, transform, transition, isDragging } = useSortable({ id: row.key, disabled: ctx.renaming === row.node.id });
  return (
    <li
      ref={setNodeRef} {...listeners}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={`relative animate-in fade-in duration-200 ${isDragging ? 'z-20' : ctx.menu === row.key ? 'z-30' : ''}`}
    >
      {/* The hairline starts at the row's indent, so it shows what is inside what. */}
      <div style={{ marginLeft: depth * INDENT }} className={`border-t transition-[margin-left] duration-150 ${isDragging ? 'border-transparent' : 'border-gray-100'}`}>
        {row.node.type === 'folder'
          ? <FolderRow folder={row.node} depth={depth} lifted={isDragging} ctx={ctx}/>
          : <ItemRow item={ctx.media.get(row.node.id)!} nodeKey={row.key} lifted={isDragging} ctx={ctx}/>}
      </div>
    </li>
  );
}

// The shared shell of a row: lifted while dragged, tinted when a dragged row
// would land in it, and glowing just after a move, with a grip in the gutter
// on hover. It reaches 8px past the list on each side so the hover fill has
// room, while the content lines up with the page title.
function RowShell({ nodeKey, lifted, ctx, children }: { nodeKey: string; lifted: boolean; ctx: RowContext; children: ReactNode }) {
  const state = lifted ? 'cursor-grabbing bg-white shadow-lg shadow-gray-900/10 ring-1 ring-gray-900/5 scale-[1.01]'
    : ctx.into === nodeKey ? 'bg-indigo-50'
      : ctx.moved === nodeKey ? 'bg-indigo-50'
        : ctx.active ? '' : 'hover:bg-gray-50';
  return (
    <div className={`group relative -mx-2 flex min-h-14 items-center gap-3 rounded-lg px-2 py-2 transition-[background-color,box-shadow,transform] duration-150 ${state}`}>
      {!ctx.active && <GripVertical size={14} aria-hidden className="absolute -left-4 hidden cursor-grab text-gray-300 opacity-0 group-hover:opacity-100 sm:block"/>}
      {children}
    </div>
  );
}

function FolderRow({ folder, depth, lifted, ctx }: { folder: FolderNode; depth: number; lifted: boolean; ctx: RowContext }) {
  const key = keyOf(folder);
  const Icon = folder.open && !lifted ? FolderOpen : Folder;
  const count = countItems(folder);
  const toggle = () => ctx.commit(updateFolder(ctx.tree, folder.id, { open: !folder.open }));
  return (
    <RowShell nodeKey={key} lifted={lifted} ctx={ctx}>
      <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${FOLDER_TILE}`}>
        <Icon size={16} strokeWidth={2}/>
      </span>
      {ctx.renaming === folder.id ? (
        <RenameInput folder={folder} ctx={ctx}/>
      ) : (
        <button onClick={toggle} onDoubleClick={() => ctx.onRename(folder.id)} aria-expanded={folder.open} className="min-w-0 flex-1 self-stretch truncate text-left text-sm font-medium text-gray-900">
          {folder.name}
        </button>
      )}
      <RowMenu nodeKey={key} label={folder.name} ctx={ctx} under={count === 0 ? 'Empty' : `${count} ${count === 1 ? 'item' : 'items'}`}>
        {(close) => (
          <>
            <MenuButton onClick={() => { close(); ctx.onRename(folder.id); }}>Rename</MenuButton>
            {depth + 1 < MAX_FOLDER_DEPTH && (
              <MenuButton onClick={() => {
                close();
                const id = newFolderId();
                ctx.commit(addFolder(ctx.tree, { type: 'folder', id, name: 'New folder', color: folder.color, open: true, children: [] }, folder.id));
                ctx.onRename(id);
              }}>New folder inside</MenuButton>
            )}
            <MoveActions nodeKey={key} ctx={ctx} close={close}/>
            <div className="my-1 h-px bg-gray-100"/>
            {/* Its items stay in the Library, one level up. */}
            <MenuButton danger onClick={() => { close(); ctx.commit(removeFolder(ctx.tree, folder.id)); }}>Delete folder</MenuButton>
          </>
        )}
      </RowMenu>
    </RowShell>
  );
}

function ItemRow({ item, nodeKey, lifted, ctx }: { item: ImportedMediaSummary; nodeKey: string; lifted: boolean; ctx: RowContext }) {
  const { icon: Icon, label, tile } = KIND[item.type] ?? KIND.text;
  const details = detailsOf(item);
  return (
    <RowShell nodeKey={nodeKey} lifted={lifted} ctx={ctx}>
      <Link href={`/media/${encodeURIComponent(item.id)}`} draggable={false} aria-label={`Open vocabulary for ${item.title}`} className="flex min-w-0 flex-1 items-center gap-3 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300">
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${tile}`} aria-label={label}>
          <Icon size={16} strokeWidth={2}/>
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-gray-900">{item.title}</span>
          {details && <span className="block truncate text-sm text-gray-500">{details}</span>}
        </span>
      </Link>
      <RowMenu nodeKey={nodeKey} label={item.title} ctx={ctx} under={new Date(item.importedAt).toLocaleDateString()}>
        {(close) => <MoveActions nodeKey={nodeKey} ctx={ctx} close={close}/>}
      </RowMenu>
    </RowShell>
  );
}

function RenameInput({ folder, ctx }: { folder: FolderNode; ctx: RowContext }) {
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

// Up, down, into a folder and out of one: the way to rearrange without dragging, on a
// phone or from the keyboard.
function MoveActions({ nodeKey, ctx, close }: { nodeKey: string; ctx: RowContext; close: () => void }) {
  const moving = findNode(ctx.tree, nodeKey);
  if (!moving) return null;
  const run = (next: LayoutNode[]) => { close(); ctx.commit(next, nodeKey); };
  const targets = listFolders(ctx.tree).filter(({ folder }) => !(moving.type === 'folder' && contains(moving, keyOf(folder)))
    && moveNode(ctx.tree, nodeKey, keyOf(folder), 'inside') !== ctx.tree);
  const parent = parentOf(ctx.tree, nodeKey);
  // Out of its folder is one level up, just below the folder; the top level
  // is listed as well only when that is further up than one level.
  const deep = !!parent && !!parentOf(ctx.tree, keyOf(parent));
  return (
    <>
      <MenuButton onClick={() => run(shift(ctx.tree, nodeKey, -1))}>Move up</MenuButton>
      <MenuButton onClick={() => run(shift(ctx.tree, nodeKey, 1))}>Move down</MenuButton>
      {parent && <MenuButton onClick={() => run(moveNode(ctx.tree, nodeKey, keyOf(parent), 'after'))}>Move out of folder</MenuButton>}
      {(targets.length > 0 || deep) && (
        <>
          <div className="my-1 h-px bg-gray-100"/>
          <p className="px-2.5 pb-1 pt-1.5 text-xs text-gray-500">Move to</p>
          <div className="max-h-48 overflow-y-auto">
            {deep && <MenuButton onClick={() => run(moveToRoot(ctx.tree, nodeKey, 'start'))}>Top level</MenuButton>}
            {targets.map(({ folder, depth }) => (
              <button key={folder.id} role="menuitem" onClick={() => run(moveNode(ctx.tree, nodeKey, keyOf(folder), 'inside'))}
                className="block w-full truncate rounded-md py-1.5 pr-2.5 text-left text-sm text-gray-700 hover:bg-gray-100" style={{ paddingLeft: 10 + depth * 12 }}>
                {folder.name}
              </button>
            ))}
          </div>
        </>
      )}
    </>
  );
}

// The "…" button sits over the row's date (or a folder's count) and replaces
// it on hover, so the right edge lines up with the header. Touch screens have
// no hover: there the button always shows and the date is left out.
function RowMenu({ nodeKey, label, under, ctx, children }: { nodeKey: string; label: string; under: string; ctx: RowContext; children: (close: () => void) => ReactNode }) {
  const open = ctx.menu === nodeKey;
  const ref = useRef<HTMLDivElement>(null);
  const { setMenu } = ctx;
  const close = useCallback(() => setMenu(null), [setMenu]);
  useDismiss(ref, open, close);
  return (
    <div ref={ref} className="relative flex shrink-0 items-center justify-end sm:min-w-20">
      <button
        onClick={() => setMenu(open ? null : nodeKey)} aria-label={`Actions for ${label}`} aria-expanded={open}
        className={`peer grid h-7 w-7 place-items-center rounded-md text-gray-400 hover:bg-gray-200/70 hover:text-gray-700 group-hover:opacity-100 sm:absolute sm:right-0 sm:top-1/2 sm:-translate-y-1/2 [@media(hover:none)]:opacity-100 ${open ? 'bg-gray-200/70 opacity-100' : 'opacity-0 focus-visible:opacity-100'}`}
      >
        <MoreHorizontal size={16}/>
      </button>
      <span className={`hidden text-sm tabular-nums text-gray-400 sm:block [@media(hover:none)]:invisible ${open ? 'invisible' : 'group-hover:invisible peer-focus-visible:invisible'}`}>{under}</span>
      <AnimatePresence>
        {open && <MenuPanel className="right-0 top-full mt-1 w-48">{children(close)}</MenuPanel>}
      </AnimatePresence>
    </div>
  );
}
