import { Language } from './languages';
import { debugLog } from './config';
import { requestBackend } from './api-service';

interface BackendTranslationResponse {
  id: string;
  root: string;
  translation: string;
}

export interface Translation {
  id: number;
  root: string;
  translation: string;
  text?: string;
  transcription?: string;
  pos?: string;
  values?: string[];
}

// Returned instead of a translation when there is no session: the API only
// translates for signed-in users, and the popup should say so.
export const SIGNED_OUT = 'signed-out';

export async function translate(
  word: string,
  language: Language
): Promise<Translation | typeof SIGNED_OUT | null> {
  try {
    const response = await requestBackend('/api/translate-word', { word, language });

    debugLog('Translation response status:', response.status);

    if (response.status === 401) return SIGNED_OUT;

    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }

    const data: BackendTranslationResponse = JSON.parse(response.body);
    return {
      id: parseInt(data.id),
      root: data.root,
      translation: data.translation,
    };
  } catch (error) {
    console.error('Translation error:', error);
    return null;
  }
}
