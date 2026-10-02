// The plugin's link to a Langfour account. The token arrives through pairing
// (see apps/api/remnote_sync.py) and lives in synced storage, so connecting
// once covers every device the knowledge base is open on.

import type { RNPlugin } from '@remnote/plugin-sdk';
import { ApiError, claimPairing, type Pairing } from './api';
import { DEFAULT_API_URL, SETTING_API_URL, STORAGE_TOKEN } from './constants';

export class NotConnectedError extends Error {
  constructor() {
    super('Not connected to Langfour. Run "Langfour: Connect".');
  }
}

export async function apiUrl(plugin: RNPlugin): Promise<string> {
  return ((await plugin.settings.getSetting<string>(SETTING_API_URL)) ?? '').trim() || DEFAULT_API_URL;
}

export async function readToken(plugin: RNPlugin): Promise<string | undefined> {
  return (await plugin.storage.getSynced<string>(STORAGE_TOKEN)) || undefined;
}

export async function forgetToken(plugin: RNPlugin): Promise<void> {
  await plugin.storage.setSynced(STORAGE_TOKEN, null);
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Poll until the user approves the code, then store the token. Resolves
 *  false when the pairing expires or `isCancelled` turns true. */
export async function waitForApproval(
  plugin: RNPlugin,
  pairing: Pairing,
  isCancelled: () => boolean,
): Promise<boolean> {
  const base = await apiUrl(plugin);
  const deadline = Date.now() + pairing.expires_in * 1000;
  while (Date.now() < deadline && !isCancelled()) {
    await sleep(pairing.poll_interval * 1000);
    try {
      const token = await claimPairing(base, pairing.secret);
      if (token) {
        await plugin.storage.setSynced(STORAGE_TOKEN, token);
        return true;
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return false; // expired or used
      // Anything else (offline for a moment) is retried on the next tick.
    }
  }
  return false;
}
