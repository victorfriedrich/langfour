// The Library as a tree of folders and items, saved as one document per
// language (docs/user-media-layout.sql). Every change returns a new tree;
// the page saves the whole of it.

export const FOLDER_COLORS = ['indigo', 'sky', 'emerald', 'amber', 'rose', 'violet', 'gray'] as const;
export type FolderColor = (typeof FOLDER_COLORS)[number];
// Must match MAX_FOLDER_DEPTH in apps/api/media_import.py.
export const MAX_FOLDER_DEPTH = 4;

export interface ItemNode { type: 'item'; id: string }
export interface FolderNode { type: 'folder'; id: string; name: string; color: FolderColor; open: boolean; children: LayoutNode[] }
export type LayoutNode = ItemNode | FolderNode;

// Items and folders have separate ids, so a node is told apart by both.
export const keyOf = (node: LayoutNode) => `${node.type}:${node.id}`;

export type DropPosition = 'before' | 'after' | 'inside';

/** The saved tree with what the Library holds now: entries for deleted items
 * are skipped, and items the tree doesn't mention yet (new imports) go at the
 * top level, ahead of everything, in the order `mediaIds` lists them. */
export function reconcile(layout: LayoutNode[], mediaIds: string[]): LayoutNode[] {
  const known = new Set(mediaIds);
  const placed = new Set<string>();
  const walk = (nodes: LayoutNode[]): LayoutNode[] => nodes.flatMap((node): LayoutNode[] => {
    if (node.type === 'folder') return [{ ...node, children: walk(node.children) }];
    if (!known.has(node.id) || placed.has(node.id)) return [];
    placed.add(node.id);
    return [node];
  });
  const tree = walk(layout);
  return [...mediaIds.filter((id) => !placed.has(id)).map((id): ItemNode => ({ type: 'item', id })), ...tree];
}

/** Every folder in display order, with how deep it sits (0 = top level). */
export function listFolders(tree: LayoutNode[], depth = 0): { folder: FolderNode; depth: number }[] {
  return tree.flatMap((node) => node.type === 'folder' ? [{ folder: node, depth }, ...listFolders(node.children, depth + 1)] : []);
}

export const countItems = (folder: FolderNode): number =>
  folder.children.reduce((sum, node) => sum + (node.type === 'item' ? 1 : countItems(node)), 0);

// How many levels of folders a node is: 0 for an item, 1 for an empty folder.
const height = (node: LayoutNode): number =>
  node.type === 'item' ? 0 : 1 + Math.max(0, ...node.children.map(height));

function remove(tree: LayoutNode[], key: string): [LayoutNode[], LayoutNode | null] {
  let removed: LayoutNode | null = null;
  const walk = (nodes: LayoutNode[]): LayoutNode[] => nodes.flatMap((node): LayoutNode[] => {
    if (keyOf(node) === key) { removed = node; return []; }
    return node.type === 'folder' ? [{ ...node, children: walk(node.children) }] : [node];
  });
  const rest = walk(tree);
  return [rest, removed];
}

// Puts `moving` next to or into the node `target`; the tree is unchanged if
// the target isn't in it. Returns the folder depth it landed at.
function insert(tree: LayoutNode[], moving: LayoutNode, target: string, position: DropPosition): [LayoutNode[], number | null] {
  let landed: number | null = null;
  const walk = (nodes: LayoutNode[], depth: number): LayoutNode[] => nodes.flatMap((node): LayoutNode[] => {
    if (keyOf(node) === target) {
      if (position === 'inside' && node.type === 'folder') {
        landed = depth + 1;
        return [{ ...node, open: true, children: [moving, ...node.children] }];
      }
      if (position === 'inside') return [node];
      landed = depth;
      return position === 'before' ? [moving, node] : [node, moving];
    }
    return node.type === 'folder' ? [{ ...node, children: walk(node.children, depth + 1) }] : [node];
  });
  const next = walk(tree, 0);
  return [next, landed];
}

/** Moves the node `key` before, after or into (at the top of) `target`. A
 * move that would put a folder inside itself, nest folders deeper than
 * MAX_FOLDER_DEPTH, or that names a missing node returns `tree` itself. */
export function moveNode(tree: LayoutNode[], key: string, target: string, position: DropPosition): LayoutNode[] {
  if (key === target) return tree;
  const [rest, moving] = remove(tree, key);
  if (!moving) return tree;
  const [next, depth] = insert(rest, moving, target, position);
  if (depth === null || depth + height(moving) > MAX_FOLDER_DEPTH) return tree;
  return next;
}

/** Moves `key` to the start or end of the top level. */
export function moveToRoot(tree: LayoutNode[], key: string, where: 'start' | 'end'): LayoutNode[] {
  const [rest, moving] = remove(tree, key);
  if (!moving) return tree;
  return where === 'start' ? [moving, ...rest] : [...rest, moving];
}

export function findNode(tree: LayoutNode[], key: string): LayoutNode | null {
  for (const node of tree) {
    if (keyOf(node) === key) return node;
    const found = node.type === 'folder' ? findNode(node.children, key) : null;
    if (found) return found;
  }
  return null;
}

/** Swaps `key` with its neighbour among its siblings (-1 up, 1 down). */
export function shift(tree: LayoutNode[], key: string, by: -1 | 1): LayoutNode[] {
  const walk = (nodes: LayoutNode[]): LayoutNode[] => {
    const at = nodes.findIndex((node) => keyOf(node) === key);
    if (at >= 0) {
      const to = at + by;
      if (to < 0 || to >= nodes.length) return nodes;
      const next = [...nodes];
      [next[at], next[to]] = [next[to], next[at]];
      return next;
    }
    return nodes.map((node) => node.type === 'folder' ? { ...node, children: walk(node.children) } : node);
  };
  return walk(tree);
}

/** Adds `folder` at the top of `parentId`'s children, or of the top level.
 * The tree is unchanged if that would nest folders too deep. */
export function addFolder(tree: LayoutNode[], folder: FolderNode, parentId?: string): LayoutNode[] {
  if (!parentId) return [folder, ...tree];
  const [next, depth] = insert(tree, folder, `folder:${parentId}`, 'inside');
  return depth === null || depth + 1 > MAX_FOLDER_DEPTH ? tree : next;
}

export function updateFolder(tree: LayoutNode[], id: string, patch: Partial<Pick<FolderNode, 'name' | 'color' | 'open'>>): LayoutNode[] {
  return tree.map((node) => {
    if (node.type !== 'folder') return node;
    if (node.id === id) return { ...node, ...patch };
    return { ...node, children: updateFolder(node.children, id, patch) };
  });
}

/** Deletes a folder; what was in it takes its place, so nothing is lost. */
export function removeFolder(tree: LayoutNode[], id: string): LayoutNode[] {
  return tree.flatMap((node): LayoutNode[] => {
    if (node.type !== 'folder') return [node];
    if (node.id === id) return removeFolder(node.children, id);
    return [{ ...node, children: removeFolder(node.children, id) }];
  });
}

/** Whether `key` is `folder` or anywhere inside it. */
export function contains(folder: FolderNode, key: string): boolean {
  return keyOf(folder) === key || folder.children.some((node) => keyOf(node) === key || (node.type === 'folder' && contains(node, key)));
}

export const newFolderId = () => `f${Math.random().toString(36).slice(2, 10)}`;
