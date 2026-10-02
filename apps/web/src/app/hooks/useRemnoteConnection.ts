import { useCallback, useContext, useEffect, useState } from 'react';
import { UserContext } from '@/context/UserContext';

export interface RemnoteConnection {
  connected: boolean;
  token_created_at: string | null;
  token_last_used_at: string | null;
  linked_words: number;
  pending_words: number;
}

/**
 * The user's RemNote sync state (apps/api/remnote_sync.py). When
 * review_provider is 'remnote', RemNote schedules reviews and Langfour's own
 * review session is hidden.
 */
export const useRemnoteConnection = () => {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const { fetchWithAuth, user } = useContext(UserContext);
  const [status, setStatus] = useState<RemnoteConnection | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!user || user.is_anonymous) return;
    setError(null);
    try {
      const response = await fetchWithAuth(`${API_URL}/integrations/remnote`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      setStatus(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the RemNote connection');
    }
  }, [API_URL, fetchWithAuth, user]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const disconnect = useCallback(async () => {
    const response = await fetchWithAuth(`${API_URL}/integrations/remnote/token`, { method: 'DELETE' });
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    await refresh();
  }, [API_URL, fetchWithAuth, refresh]);

  return { status, error, refresh, disconnect };
};
