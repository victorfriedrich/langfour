'use client';

import React, { useContext, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { UserContext } from '@/context/UserContext';
import { LANGUAGE_LIST, isLanguageCode } from '@/lib/languages';
import OnboardingFlow from '../components/onboarding/OnboardingFlow';

const AddLanguagePage: React.FC = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading, availableLanguages } = useContext(UserContext);

  // Adding a language needs an account: demo accounts and visitors start
  // from the beginning instead.
  useEffect(() => {
    if (loading) return;
    if (!user) router.push('/login');
    else if (user.is_anonymous) router.push('/get-started');
  }, [user, loading, router]);

  if (loading || !user || user.is_anonymous || !availableLanguages.length) {
    return <div className="min-h-dvh bg-white" />;
  }

  const have = LANGUAGE_LIST.map((l) => l.code).filter((c) => availableLanguages.some((a) => a.code === c && a.initialized));
  const requested = searchParams.get('language');
  return (
    <OnboardingFlow
      adding={{ have, start: isLanguageCode(requested) ? requested : undefined }}
    />
  );
};

export default AddLanguagePage;
