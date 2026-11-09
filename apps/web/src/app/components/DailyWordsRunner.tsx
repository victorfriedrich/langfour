'use client';

import { useContext, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { UserContext } from '@/context/UserContext';
import { useUpdateUserwords } from '@/app/hooks/useUpdateUserwords';
import { ensureDailyWords } from '@/lib/dailyWords';

/** Adds the day's new words to the review queue when the app opens. Renders
 *  nothing: the words simply show up in Practice's due count. */
export default function DailyWordsRunner() {
  const { user, language, fetchWithAuth } = useContext(UserContext);
  const { addWordsToUserwords } = useUpdateUserwords();
  const pathname = usePathname();
  const code = language?.code;
  // Get started adds the first batch itself, once the choices are saved.
  const onboarding = pathname.startsWith('/get-started');

  useEffect(() => {
    if (!user || !code || onboarding) return;
    ensureDailyWords(code, fetchWithAuth, addWordsToUserwords).catch((err) =>
      console.error('Daily words failed:', err),
    );
    // Once per account and language per page load; the date check inside
    // keeps it to once a day.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, code, onboarding]);

  return null;
}
