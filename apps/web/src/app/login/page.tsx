"use client";

import { useContext, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabaseclient';
import { peekAfterLogin } from '@/lib/afterLogin';
import { UserContext } from '@/context/UserContext';
import EmailStep from '../components/entry/EmailStep';
import { NewHere } from '../components/entry/EntryFrame';

function Login() {
  const { user } = useContext(UserContext);
  const router = useRouter();

  useEffect(() => {
    if (user && !user.is_anonymous) {
      // The magic link may sign in the original tab as well as its callback.
      // Both must resume the pending connection rather than discard it.
      router.push(peekAfterLogin());
    }
  }, [user, router]);

  const send = async (email: string) => {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    // Supabase refuses a second email within 60 seconds (also across the
    // extension's sign-in page), so the reason has to be shown.
    if (error) throw error;
  };

  return (
    <EmailStep
      title="Welcome back"
      lead="Enter your email and we’ll send you a link to log in."
      action="Email me a link"
      sentLead="Open the link on this device to log in."
      onSend={send}
      navRight={<NewHere />}
      footer={<>New here? <Link href="/get-started">Start learning</Link></>}
    />
  );
}

export default Login;
