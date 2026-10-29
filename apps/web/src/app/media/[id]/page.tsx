'use client';

import { useCallback, useContext, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import ProtectedRoute from '../../components/ProtectedRoute';
import Wordpanel from '../../components/Wordpanel';
import ConfirmationPopup from '../../components/ConfirmationPopup';
import { UserContext } from '@/context/UserContext';
import { getImportedMedia, ImportedMedia } from '../api';

const KIND: Record<string, string> = { series: 'Episode', movie: 'Movie', article: 'Article', song: 'Song' };

function MediaVocabularyContent() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { language, fetchWithAuth } = useContext(UserContext);
  const [media, setMedia] = useState<ImportedMedia | null>(null);
  const [error, setError] = useState('');
  const [confirmationCount, setConfirmationCount] = useState(0);

  useEffect(() => {
    let active = true;
    getImportedMedia(fetchWithAuth, params.id, language?.code || 'es')
      .then((item) => active && setMedia(item))
      .catch((reason) => active && setError(reason instanceof Error ? reason.message : 'Unable to load this episode'));
    return () => { active = false; };
  }, [fetchWithAuth, params.id, language?.code]);

  const close = useCallback((count: number) => {
    if (count > 0) setConfirmationCount(count);
    else router.push('/media');
  }, [router]);

  if (error) return <div className="min-h-screen bg-white"><div className="max-w-3xl px-4 py-10 sm:px-8"><p className="text-sm text-red-600">{error}</p><button onClick={() => router.push('/media')} className="mt-4 text-sm text-indigo-600 hover:text-indigo-700">Back to Media</button></div></div>;
  if (!media) return <div className="flex min-h-screen items-center justify-center bg-white"><Loader2 className="h-6 w-6 animate-spin text-gray-400"/></div>;

  return <><Wordpanel videoId={media.id} videoTitle={media.title} transcript={media.chunks} variant="page" source="media" eyebrow={KIND[media.type] ?? 'Text'} onClose={close}/>{confirmationCount > 0 && <ConfirmationPopup count={confirmationCount} onClose={() => router.push('/media')}/>}</>;
}

export default function MediaVocabularyPage() {
  return <ProtectedRoute><MediaVocabularyContent/></ProtectedRoute>;
}
