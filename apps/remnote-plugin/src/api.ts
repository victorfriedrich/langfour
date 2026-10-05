// Client for the API's /pair/remnote and /sync/remnote endpoints (apps/api/remnote_sync.py).

export interface PendingWord {
  word_id: number;
  root: string;
  language: string;
  translation: string | null;
  added_at: string;
}

export interface LinkedWordDetails {
  word_id: number;
  language: string;
  added_at: string;
}

export interface ReviewPayload {
  at: number;
  score: number;
}

export interface CardPayload {
  card_id: string;
  kind: 'forward' | 'backward' | 'cloze';
  next_due_at: number | null;
  reviews: ReviewPayload[];
}

export interface NotePayload {
  word_id: number;
  rem_id: string;
  cards: CardPayload[];
  practiced?: boolean; // whether the Rem's flashcards are turned on
}

export interface PushResult {
  notes: number;
  cards: number;
  reviews: number;
  removed: number;
  restored: number;
  disabled: number;
  enabled: number;
  rejected_word_ids: number[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** The server lets one sync run at a time per user, across devices. */
export class SyncBusyError extends Error {}

export interface Pairing {
  user_code: string;
  secret: string;
  verify_url: string;
  expires_in: number;
  poll_interval: number;
}

async function send(baseUrl: string, path: string, init: RequestInit, headers: Record<string, string> = {}) {
  let response: Response;
  try {
    response = await fetch(baseUrl.replace(/\/+$/, '') + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...headers },
    });
  } catch {
    throw new ApiError(0, `Could not reach Langfour at ${baseUrl}`);
  }
  if (response.status === 423) throw new SyncBusyError('A Langfour sync is already running.');
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return response;
}

// Pairing (the plugin has no token yet): open a pairing, then collect the
// token once the user approved the code in Langfour.
export async function startPairing(baseUrl: string): Promise<Pairing> {
  return (await send(baseUrl, '/pair/remnote/start', { method: 'POST' })).json();
}

/** The token once the pairing is approved, null while it is still pending.
 *  Throws ApiError 404 once the pairing expired. */
export async function claimPairing(baseUrl: string, secret: string): Promise<string | null> {
  const response = await send(baseUrl, '/pair/remnote/claim', { method: 'POST', body: JSON.stringify({ secret }) });
  return response.status === 202 ? null : (await response.json()).token;
}

export class LangfourApi {
  /** Every request names the run, so the server can hold its sync lease. */
  constructor(private baseUrl: string, private token: string, private runId: string) {}

  async pending(limit: number): Promise<{ words: PendingWord[]; remaining: number }> {
    return (await this.request(`/sync/remnote/pending?limit=${limit}`)).json();
  }

  async push(body: { notes?: NotePayload[]; present_rem_ids?: string[]; disabled_rem_ids?: string[] }): Promise<PushResult> {
    return (await this.request('/sync/remnote/push', { method: 'POST', body: JSON.stringify(body) })).json();
  }

  async linked(): Promise<{ words: LinkedWordDetails[] }> {
    return (await this.request('/sync/remnote/linked')).json();
  }

  async relink(body: { word_id: number; from_rem_id: string; to_rem_id: string }): Promise<void> {
    await this.request('/sync/remnote/relink', { method: 'POST', body: JSON.stringify(body) });
  }

  /** Hand the lease back early; if this never arrives it lapses on its own. */
  async release(): Promise<void> {
    await this.request('/sync/remnote/release', { method: 'POST' });
  }

  private request(path: string, init: RequestInit = {}) {
    return send(this.baseUrl, path, init, {
      Authorization: `Bearer ${this.token}`,
      'X-Sync-Run': this.runId,
    });
  }
}
