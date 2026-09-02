'use client';

import { useCallback, useContext, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import ProtectedRoute from '../../components/ProtectedRoute';
import Wordpanel from '../../components/Wordpanel';
import ConfirmationPopup from '../../components/ConfirmationPopup';
import { UserContext } from '@/context/UserContext';
import { getImportedMedia, ImportedMedia } from '../api';

function MediaVocabularyContent() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { language } = useContext(UserContext);
  const [media, setMedia] = useState<ImportedMedia | null>(null);
  const [error, setError] = useState('');
  const [confirmationCount, setConfirmationCount] = useState(0);

  useEffect(() => {
    let active = true;
    getImportedMedia(params.id, language?.code || 'es')
      .then((item) => active && setMedia(item))
      .catch((reason) => active && setError(reason instanceof Error ? reason.message : 'Unable to load this episode'));
    return () => { active = false; };
  }, [params.id, language?.code]);

  const close = useCallback((count: number) => {
    if (count > 0) setConfirmationCount(count);
    else router.push('/media');
  }, [router]);

  if (error) return <div className="min-h-full bg-slate-50 px-5 py-16"><div className="mx-auto max-w-xl rounded-2xl border border-red-200 bg-white p-8 text-center text-red-700"><p>{error}</p><button onClick={() => router.push('/media')} className="mt-5 font-semibold text-indigo-700">Back to media</button></div></div>;
  if (!media) return <div className="flex min-h-full items-center justify-center bg-slate-50"><Loader2 className="h-7 w-7 animate-spin text-indigo-600"/></div>;

  return <><Wordpanel videoId={media.id} videoTitle={media.title} transcript={media.chunks} variant="page" onClose={close}/>{confirmationCount > 0 && <ConfirmationPopup count={confirmationCount} onClose={() => router.push('/media')}/>}</>;
}

export default function MediaVocabularyPage() {
  return <ProtectedRoute><MediaVocabularyContent/></ProtectedRoute>;
}
