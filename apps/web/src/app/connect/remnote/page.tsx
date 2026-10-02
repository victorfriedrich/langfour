'use client';

import { Suspense, useContext, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Check, Link2, Loader2 } from 'lucide-react';
import { UserContext } from '@/context/UserContext';
import { rememberAfterLogin } from '@/lib/afterLogin';

type State =
  | { step: 'loading' }
  | { step: 'confirm'; code: string }
  | { step: 'done' }
  | { step: 'error'; message: string };

const EXPIRED = 'This code has expired. Start again in RemNote with "Langfour: Connect".';

/**
 * Approves a pairing the RemNote plugin started (apps/api/remnote_sync.py).
 * The plugin shows the same code, so the user can check they are approving
 * their own RemNote and not a link someone sent them.
 */
function ConnectRemnote() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const { user, loading, fetchWithAuth } = useContext(UserContext);
  const router = useRouter();
  const code = useSearchParams().get('code') ?? '';
  const [state, setState] = useState<State>({ step: 'loading' });
  const [busy, setBusy] = useState(false);
  const signedIn = !!user && !user.is_anonymous;

  useEffect(() => {
    if (loading || !signedIn || !code) return;
    fetchWithAuth(`${API_URL}/integrations/remnote/pairings/${encodeURIComponent(code)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(EXPIRED);
        const { user_code } = await response.json();
        setState({ step: 'confirm', code: user_code });
      })
      .catch((err) => setState({ step: 'error', message: err instanceof Error ? err.message : EXPIRED }));
  }, [API_URL, code, fetchWithAuth, loading, signedIn]);

  const approve = async (pairingCode: string) => {
    setBusy(true);
    const response = await fetchWithAuth(
      `${API_URL}/integrations/remnote/pairings/${encodeURIComponent(pairingCode)}/approve`,
      { method: 'POST' },
    ).catch(() => null);
    setBusy(false);
    setState(response?.ok ? { step: 'done' } : { step: 'error', message: EXPIRED });
  };

  const signIn = () => {
    rememberAfterLogin(`/connect/remnote?code=${encodeURIComponent(code)}`);
    router.push('/login');
  };

  const button =
    'w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium text-white bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50';

  let body: React.ReactNode;
  if (!code) {
    body = <p className="text-sm text-gray-600">{EXPIRED}</p>;
  } else if (loading || (signedIn && state.step === 'loading')) {
    body = <Loader2 className="h-6 w-6 animate-spin text-indigo-500" />;
  } else if (!signedIn) {
    body = (
      <>
        <p className="text-sm text-gray-600">Sign in to connect RemNote to your Langfour account.</p>
        <button className={button} onClick={signIn}>
          Sign in
        </button>
      </>
    );
  } else if (state.step === 'confirm') {
    const chars = state.code.replace('-', '');
    body = (
      <>
        <p className="text-sm text-gray-600">Check that RemNote shows the same code:</p>
        <div className="flex gap-1.5" aria-label={`Code ${state.code}`}>
          {[...chars].map((c, i) => (
            <span
              key={i}
              className={`grid place-items-center w-8 h-11 rounded-md border border-gray-200 bg-gray-50 text-xl font-semibold text-gray-900 ${i === 4 ? 'ml-2' : ''}`}
            >
              {c}
            </span>
          ))}
        </div>
        <button className={button} onClick={() => approve(state.code)} disabled={busy}>
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Link2 size={16} />}
          Connect RemNote
        </button>
        <p className="text-xs text-gray-500 max-w-xs">
          Only approve a code from your own RemNote. Whoever holds it can read your words to learn and report reviews.
        </p>
      </>
    );
  } else if (state.step === 'done') {
    body = (
      <>
        <span className="grid place-items-center w-10 h-10 rounded-full bg-emerald-50 ring-1 ring-emerald-200 text-emerald-600">
          <Check size={20} strokeWidth={2.5} />
        </span>
        <div className="space-y-1">
          <p className="font-semibold text-gray-900">RemNote is connected</p>
          <p className="text-sm text-gray-600">
            You can close this tab. Your words appear in RemNote in a moment, and your reviews now happen there.
          </p>
        </div>
      </>
    );
  } else if (state.step === 'error') {
    body = <p className="text-sm text-gray-600">{state.message}</p>;
  }

  return (
    <div className="min-h-screen bg-gray-50 flex justify-center px-4">
      <div className="w-full max-w-sm mt-24 self-start bg-white border border-gray-200 rounded-xl shadow-sm p-8 flex flex-col items-center gap-5 text-center">
        {state.step !== 'done' && (
          <span className="grid place-items-center w-10 h-10 rounded-lg bg-indigo-50 text-indigo-500">
            <Link2 size={20} />
          </span>
        )}
        {state.step !== 'done' && <h1 className="text-xl font-semibold text-gray-900">Connect RemNote</h1>}
        {body}
      </div>
    </div>
  );
}

export default function ConnectRemnotePage() {
  // useSearchParams needs a Suspense boundary to build.
  return (
    <Suspense>
      <ConnectRemnote />
    </Suspense>
  );
}
