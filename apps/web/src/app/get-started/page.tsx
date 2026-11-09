'use client';

import React, { useContext, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { UserContext } from '@/context/UserContext';
import OnboardingFlow from '../components/onboarding/OnboardingFlow';

const GetStartedPage: React.FC = () => {
  const router = useRouter();
  const { user, loading } = useContext(UserContext);
  // Wait for the first load only: creating the demo account at the end of
  // the flow reloads the context, and the flow must stay on screen meanwhile.
  const [ready, setReady] = useState(false);
  if (!loading && !ready) setReady(true);

  // A signed-in account has nothing to set up here.
  useEffect(() => {
    if (user && !user.is_anonymous) {
      router.push('/videos');
    }
  }, [user, router]);

  if (!ready) return <div className="min-h-dvh bg-white" />;
  return <OnboardingFlow />;
};

export default GetStartedPage;
