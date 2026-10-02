'use client';

import React, { useState, useMemo, useCallback, useContext, useEffect } from 'react';
import { UserContext } from '@/context/UserContext';
import { FlashcardSession } from '../session/FlashcardSession';
import ContextReviewSession from './ContextReviewSession';
import { useOverdueWords } from '../hooks/useOverdueWords';
import { getWordsDueToday } from '../utils/dateUtils';
import LearningWordsTable from '../components/LearningWordsTable';
import ErrorState from '../components/ErrorState';
import ProtectedRoute from '../components/ProtectedRoute';
import { useReviewProvider, type ReviewProvider } from '../hooks/useReviewProvider';
import { useRemnoteConnection } from '../hooks/useRemnoteConnection';
import { usePracticeProgress } from '../hooks/usePracticeProgress';
import { wordStageAt } from '../../../../remnote-plugin/src/stats';
import TodayCard from './TodayCard';
import { wordsDueToday } from './due';
import ProgressOverview from './ProgressOverview';
import RemnoteSection from './RemnoteSection';
import SchedulerLabel from './SchedulerLabel';

/** The page's shape in grey, shown until everything above the fold can
 *  appear at once. */
function PracticeSkeleton() {
  const bar = 'animate-pulse rounded bg-gray-100';
  return (
    <div aria-label="Loading">
      <div className="h-[72px] animate-pulse rounded-xl bg-gray-50" />
      <div className={`mt-10 h-12 w-56 ${bar}`} />
      <div className={`mt-5 h-20 w-full ${bar}`} />
      <div className={`mt-6 h-2 w-full ${bar}`} />
      <div className={`mt-3 h-4 w-72 ${bar}`} />
      <div className="mt-10 border-t border-gray-100 pt-8">
        <div className={`h-5 w-32 ${bar}`} />
        <div className="mt-4 divide-y divide-gray-100">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="flex items-center gap-6 py-3 pl-11">
              <span className={`h-3 w-28 ${bar}`} />
              <span className={`h-3 w-40 ${bar}`} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Show whatever has arrived after this long rather than a skeleton forever.
const MAX_SKELETON_MS = 6000;

const PracticePage = () => {
  const [showSession, setShowSession] = useState(false);
  const [showContextReview, setShowContextReview] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

  const provider = useReviewProvider();
  const { status: remnote, error: remnoteError, disconnect } = useRemnoteConnection();
  const { user, language } = useContext(UserContext);
  const languageCode = language?.code;
  const { words: allProgressWords, error: progressError } = usePracticeProgress(provider, refreshTrigger);
  // The language chosen in the sidebar, like everything else in the app.
  const progressWords = useMemo(
    () => allProgressWords && (languageCode ? allProgressWords.filter((w) => w.language === languageCode) : allProgressWords),
    [allProgressWords, languageCode],
  );
  const { words: overdueWords, isLoading: overdueLoading, error: overdueError } = useOverdueWords(refreshTrigger, { source: sourceFilter ?? undefined });

  const refresh = useCallback(() => setRefreshTrigger((n) => n + 1), []);

  // Everything appears together, once: a skeleton until the first answers
  // are in, then no more placeholders when filters or reviews refresh.
  const [tableReady, setTableReady] = useState(false);
  const onTableReady = useCallback(() => setTableReady(true), []);
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setTimedOut(true), MAX_SKELETON_MS);
    return () => clearTimeout(t);
  }, []);
  const anonymous = !!user?.is_anonymous;
  const loaded =
    provider !== null &&
    !overdueLoading &&
    tableReady &&
    (anonymous || progressWords !== null || progressError !== null) &&
    // RemNote's last sync and word count, when it schedules. Otherwise its
    // section is the invitation, which needs nothing from the API.
    (provider !== 'remnote' || remnote !== null || remnoteError !== null);
  const [revealed, setRevealed] = useState(false);
  if ((loaded || timedOut) && !revealed) setRevealed(true);

  // Langfour's own review set; RemNote reviews are counted from its due dates.
  const learningSet = useMemo(
    () =>
      getWordsDueToday(overdueWords ?? [])
        .filter((w) => w?.word_id && (w.word_root || w.root))
        .map((w) => ({ id: w.word_id, word: w.word_root || w.root, translation: w.translation || 'No translation available' })),
    [overdueWords],
  );
  const [now] = useState(() => Date.now());
  const stages = useMemo(
    () => new Map((progressWords ?? []).map((w) => [w.wordId, wordStageAt(w.cards, now)] as const)),
    [progressWords, now],
  );
  const dueInRemnote = useMemo(() => wordsDueToday(progressWords ?? [], now), [progressWords, now]);

  if (showSession) {
    return (
      <FlashcardSession
        mode="flashcard"
        frontSide="english"
        learningSet={learningSet}
        onExit={() => {
          setShowSession(false);
          refresh();
        }}
      />
    );
  }
  if (showContextReview) {
    return (
      <ContextReviewSession
        learningSet={learningSet}
        onExit={() => {
          setShowContextReview(false);
          refresh();
        }}
      />
    );
  }
  if (overdueError && overdueError !== 'No language selected') return <ErrorState message={overdueError} />;

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-white">
        {/* Flat: no cards. Sections are separated by space and a hairline. */}
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <header className="mb-8 flex min-h-8 flex-wrap items-end justify-between gap-2">
            <h1 className="text-2xl font-semibold text-gray-900">Practice</h1>
            {revealed && provider && (
              <SchedulerLabel
                provider={provider}
                remnote={remnote}
                onDisconnect={async () => {
                  await disconnect();
                  window.location.reload(); // the scheduler changed; reload every view
                }}
              />
            )}
          </header>

          {!revealed && <PracticeSkeleton />}

          {/* Mounted while hidden, so every part loads at the same time. */}
          <div
            className={
              revealed
                ? 'animate-in fade-in duration-300'
                : 'hidden'
            }
          >
            {provider && (
              <TodayCard
                provider={provider}
                due={provider === 'remnote' ? dueInRemnote : learningSet.length}
                onStartReview={() => setShowSession(true)}
                onContextReview={() => setShowContextReview(true)}
              />
            )}

            {(progressError || progressWords) && (
              <section className="mt-10">
                {progressError ? (
                  <p className="text-sm text-red-600">{progressError}</p>
                ) : (
                  progressWords && <ProgressOverview words={progressWords} />
                )}
              </section>
            )}

            {provider === 'langfour' && !anonymous && (
              <div className="mt-10">
                <RemnoteSection />
              </div>
            )}

            {/* The one hairline: what you know above, the words below. */}
            <div className="mt-10 border-t border-gray-100 pt-8">
              <LearningWordsTable
                onMovedToKnown={refresh}
                onSourceChange={setSourceFilter}
                source={sourceFilter}
                showDue={provider !== 'remnote'}
                stages={stages}
                total={progressWords?.length}
                onReady={onTableReady}
              />
            </div>
          </div>
        </div>
      </div>
    </ProtectedRoute>
  );
};

export default PracticePage;
