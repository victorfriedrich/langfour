'use client';

import { Suspense, useContext, useEffect, useState } from 'react';
import type { OAuthAuthorizationDetails } from '@supabase/supabase-js';
import { useRouter, useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { UserContext } from '@/context/UserContext';
import { supabase } from '@/lib/supabaseclient';
import { rememberAfterLogin } from '@/lib/afterLogin';

const FAILED = 'This connection request could not be completed. Start again from your AI app.';
const button = 'w-full rounded-lg px-4 py-2.5 text-sm font-medium disabled:opacity-50';

function ConsentRequest({ authorizationId }: { authorizationId: string }) {
  const { user, loading } = useContext(UserContext);
  const router = useRouter();
  const signedIn = !!user && !user.is_anonymous;
  const [details, setDetails] = useState<OAuthAuthorizationDetails | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (loading || !signedIn || !authorizationId) return;
    supabase.auth.oauth.getAuthorizationDetails(authorizationId)
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error || !data) throw new Error(FAILED);
        if ('redirect_url' in data) {
          // Only Supabase's validated result can supply a redirect. Never use
          // client_name, redirect_uri or decision values from URL parameters.
          window.location.assign(data.redirect_url);
        } else {
          setDetails(data);
        }
      })
      .catch(() => { if (!cancelled) setError(FAILED); });
    return () => { cancelled = true; };
  }, [authorizationId, loading, signedIn, user?.id]);

  async function decide(approve: boolean) {
    if (!details || busy) return;
    setBusy(true);
    try {
      const { data, error } = approve
        ? await supabase.auth.oauth.approveAuthorization(details.authorization_id, { skipBrowserRedirect: true })
        : await supabase.auth.oauth.denyAuthorization(details.authorization_id, { skipBrowserRedirect: true });
      if (error || !data) throw new Error(FAILED);
      window.location.assign(data.redirect_url);
    } catch {
      setError(FAILED);
      setBusy(false);
    }
  }

  function signIn() {
    rememberAfterLogin(`/oauth/consent?authorization_id=${encodeURIComponent(authorizationId)}`);
    router.push('/login');
  }

  return (
    <div className="min-h-screen bg-gray-50 flex justify-center px-4">
      <div className="w-full max-w-md mt-20 self-start rounded-xl border border-gray-200 bg-white p-8 shadow-sm space-y-5">
        <h1 className="text-xl font-semibold text-gray-900">Connect to Langfour</h1>
        {!authorizationId || error ? (
          <p role="alert" className="text-sm text-gray-600">{error || FAILED}</p>
        ) : loading ? (
          <Loader2 aria-label="Loading" className="animate-spin text-indigo-500" />
        ) : !signedIn ? (
          <>
            <p className="text-sm text-gray-600">Sign in to choose whether to connect your AI app.</p>
            <button onClick={signIn} className={`${button} bg-indigo-500 text-white hover:bg-indigo-600`}>Sign in</button>
          </>
        ) : !details ? (
          <Loader2 aria-label="Loading connection" className="animate-spin text-indigo-500" />
        ) : (
          <>
            <p className="text-sm text-gray-700"><strong>{details.client.name || 'An AI app'}</strong> wants to connect to your Langfour account.</p>
            <p className="text-sm text-gray-600">Signed in as {details.user.email}</p>
            <ul className="list-disc pl-5 text-sm text-gray-600 space-y-2">
              <li>See which words you know and are learning.</li>
              <li>Record vocabulary practice results and texts you read.</li>
              <li>Update your learning progress and schedule flashcard reviews, including in RemNote when connected.</li>
              {details.scope.split(/\s+/).filter(Boolean).map(scope => (
                <li key={scope}>Account permission: {scope}</li>
              ))}
            </ul>
            <div className="text-xs text-gray-500 break-all">
              <p>Return address: {details.redirect_uri}</p>
              <p className="mt-2">Only approve a connection you started in an app you trust.</p>
            </div>
            <button disabled={busy} onClick={() => decide(true)} className={`${button} bg-indigo-500 text-white hover:bg-indigo-600`}>
              {busy ? 'Returning to your app…' : 'Allow access'}
            </button>
            <button disabled={busy} onClick={() => decide(false)} className={`${button} border border-gray-300 text-gray-700 hover:bg-gray-50`}>Deny</button>
          </>
        )}
      </div>
    </div>
  );
}

function Consent() {
  const authorizationId = useSearchParams().get('authorization_id') ?? '';
  const { user } = useContext(UserContext);
  // A different request or account must never reuse an earlier consent form.
  return <ConsentRequest key={`${authorizationId}:${user?.id ?? ''}`} authorizationId={authorizationId} />;
}

export default function ConsentPage() {
  return <Suspense><Consent /></Suspense>;
}
