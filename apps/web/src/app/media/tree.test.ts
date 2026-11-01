import { expect, it } from 'vitest';
import { MAX_FOLDER_DEPTH, addFolder, drop, flatten, moveNode, moveToRoot, project, reconcile, removeFolder, shift } from './tree';
import type { FolderNode, LayoutNode } from './tree';

const item = (id: string): LayoutNode => ({ type: 'item', id });
const folder = (id: string, ...children: LayoutNode[]): FolderNode => ({ type: 'folder', id, name: id, color: 'indigo', open: false, children });

it('puts new imports at the top and skips deleted or repeated items', () => {
  const saved = [folder('f', item('a'), item('gone')), item('a'), item('b')];
  expect(reconcile(saved, ['new', 'a', 'b'])).toEqual([item('new'), folder('f', item('a')), item('b')]);
});

it('moves an item before, after and into the top of a folder', () => {
  const tree = [item('a'), item('b'), folder('f', item('c'))];
  expect(moveNode(tree, 'item:a', 'item:b', 'after')).toEqual([item('b'), item('a'), folder('f', item('c'))]);
  expect(moveNode(tree, 'item:c', 'item:a', 'before')).toEqual([item('c'), item('a'), item('b'), folder('f')]);
  // Dropping into a closed folder opens it, so the item can be seen landing.
  expect(moveNode(tree, 'item:b', 'folder:f', 'inside')).toEqual([item('a'), { ...folder('f', item('b'), item('c')), open: true }]);
});

it('refuses to put a folder inside itself or nest folders too deep', () => {
  const tree = [folder('f', folder('g', item('a')))];
  expect(moveNode(tree, 'folder:f', 'folder:g', 'inside')).toBe(tree);
  expect(moveNode(tree, 'folder:f', 'item:a', 'after')).toBe(tree);
  expect(moveNode(tree, 'item:a', 'item:missing', 'after')).toBe(tree);

  let deep: LayoutNode[] = [folder('f0')];
  for (let level = 1; level < MAX_FOLDER_DEPTH; level++) deep = addFolder(deep, folder(`f${level}`), `f${level - 1}`);
  expect(addFolder(deep, folder('too-deep'), `f${MAX_FOLDER_DEPTH - 1}`)).toBe(deep);
  const tall = [folder('x', folder('y')), ...deep];
  expect(moveNode(tall, 'folder:x', `folder:f${MAX_FOLDER_DEPTH - 2}`, 'inside')).toBe(tall);
});

it('deleting a folder keeps what was in it', () => {
  expect(removeFolder([item('a'), folder('f', item('b'), folder('g')), item('c')], 'f')).toEqual([item('a'), item('b'), folder('g'), item('c')]);
});

it('shifts among siblings and moves to the top level', () => {
  const tree = [item('a'), folder('f', item('b'), item('c'))];
  expect(shift(tree, 'item:c', -1)).toEqual([item('a'), folder('f', item('c'), item('b'))]);
  expect(shift(tree, 'item:a', -1)).toEqual(tree);
  expect(moveToRoot(tree, 'item:c', 'start')).toEqual([item('c'), item('a'), folder('f', item('b'))]);
});

it('projects a dragged row into the folder it is dropped under', () => {
  const open = { ...folder('f', item('c')), open: true };
  const tree = [item('a'), folder('closed', item('x')), item('b'), open];
  const rows = flatten(tree, true);
  expect(rows.map((row) => `${row.key}@${row.depth}`)).toEqual(['item:a@0', 'folder:closed@0', 'item:b@0', 'folder:f@0', 'item:c@1']);
  // Just under a closed folder: beside it, unless dragged right.
  expect(project(rows, 'item:a', 'folder:closed', 0, 44)).toEqual({ depth: 0, parent: null, after: 'folder:closed' });
  expect(project(rows, 'item:a', 'folder:closed', 50, 44)).toEqual({ depth: 1, parent: 'folder:closed', after: 'folder:closed' });
  // Just under an open folder: into it, even dragged left.
  expect(project(rows, 'item:a', 'folder:f', -200, 44)).toEqual({ depth: 1, parent: 'folder:f', after: 'folder:f' });
  // Out of a folder at the bottom by dragging left.
  expect(project(rows, 'item:c', 'item:c', -44, 44)).toEqual({ depth: 0, parent: null, after: 'folder:f' });
});

it('drops a row after another, into a folder, and carries a folder\'s contents', () => {
  const tree = [item('a'), folder('closed', item('x')), item('b')];
  expect(drop(tree, 'item:a', 'folder:closed', 'folder:closed')).toEqual([{ ...folder('closed', item('a'), item('x')), open: true }, item('b')]);
  expect(drop(tree, 'item:b', null, null)).toEqual([item('b'), item('a'), folder('closed', item('x'))]);
  expect(drop(tree, 'folder:closed', 'item:b', null)).toEqual([item('a'), item('b'), folder('closed', item('x'))]);
});

it('keeps folders within the nesting limit when dragging', () => {
  let deep: LayoutNode[] = [{ ...folder('f0'), open: true }];
  for (let level = 1; level < MAX_FOLDER_DEPTH; level++) deep = addFolder(deep, { ...folder(`f${level}`), open: true }, `f${level - 1}`);
  deep = addFolder(deep, { ...folder('z'), open: true }, `f${MAX_FOLDER_DEPTH - 2}`);
  const tree = [folder('x', folder('y')), ...deep];
  const rows = flatten(tree, true, 'folder:x');
  // Between f2 and its first row z, a two-level folder would be too deep.
  expect(project(rows, 'folder:x', `folder:f${MAX_FOLDER_DEPTH - 2}`, 0, 44)).toBeNull();
  // With nothing below forcing the depth, it settles where it fits.
  expect(project(rows, 'folder:x', 'folder:f3', 500, 44)).toMatchObject({ depth: MAX_FOLDER_DEPTH - 2, parent: 'folder:f1' });
});
