"use client"

import { useContext } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';
import EmailStep from '../components/entry/EmailStep';
import s from '../components/entry/entry.module.css';

/** Turns the demo account into a real one: the email is added to the
 *  anonymous user, so its words and settings stay with it. */
const SaveProgress = () => {
  const { user } = useContext(UserContext);

  const send = async (email: string) => {
    if (!user) throw new Error('No demo account found. Start learning first.');
    const { error } = await supabase.auth.updateUser({ email });
    if (error) throw error;
  };

  return (
    <EmailStep
      title="Save your progress"
      lead="Add your email so your words and settings stay with you, on any device."
      action="Save progress"
      sentLead="Open the link to confirm, and your progress is saved."
      onSend={send}
      navRight={<Link className={s.lk} href="/videos">Back to videos</Link>}
      footer={<>Already have an account? <Link href="/login">Log in</Link></>}
    />
  );
};

export default SaveProgress;
