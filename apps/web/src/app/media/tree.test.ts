import { expect, it } from 'vitest';
import { MAX_FOLDER_DEPTH, addFolder, moveNode, moveToRoot, reconcile, removeFolder, shift } from './tree';
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
