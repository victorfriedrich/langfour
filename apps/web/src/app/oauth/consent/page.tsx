'use client';

import { Suspense, useContext, useEffect, useState } from 'react';
import type { OAuthAuthorizationDetails } from '@supabase/supabase-js';
import { useSearchParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { UserContext } from '@/context/UserContext';
import { supabase } from '@/lib/supabaseclient';
import { rememberAfterLogin } from '@/lib/afterLogin';
import EmailStep from '../../components/entry/EmailStep';
import GrantCard from '../../components/entry/GrantCard';
import SkyFrame from '../../components/entry/SkyFrame';
import s from '../../components/entry/entry.module.css';

const FAILED = 'This connection request could not be completed. Start again from your AI app.';

function ConsentRequest({ authorizationId }: { authorizationId: string }) {
  const { user, loading } = useContext(UserContext);
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

  // Log in right here; the link brings the learner back to this request.
  async function sendLink(email: string) {
    rememberAfterLogin(`/oauth/consent?authorization_id=${encodeURIComponent(authorizationId)}`);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    if (error) throw error;
  }

  if (!authorizationId || error) {
    return <SkyFrame state="error" title="Couldn’t connect" lead={<p role="alert">{error || FAILED}</p>} />;
  }

  if (!loading && !signedIn) {
    return (
      <EmailStep
        title="Connect your AI app"
        lead="Log in first. Then you choose what your AI app can do with your Langfour words."
        action="Email me a link"
        sentLead="Open the link on this device. It brings you back here to finish connecting."
        onSend={sendLink}
        navRight={null}
        footer="Only connect an app you started this from yourself."
      />
    );
  }

  if (!details) {
    return (
      <SkyFrame state="loading" title="Connect your AI app" lead="Checking the request…">
        <div className={s.waiting}>
          <Loader2 aria-label="Loading connection" className="animate-spin" />
        </div>
      </SkyFrame>
    );
  }

  const name = details.client.name || 'An AI app';

  return (
    <SkyFrame
      state="ask"
      title={<>Connect <span>{name}</span></>}
      lead={<p>It’s asking to use your Langfour account. Only allow a connection you started yourself.</p>}
    >
      <GrantCard details={details} busy={busy} onDecide={decide} />
    </SkyFrame>
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
