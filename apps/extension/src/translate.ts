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

export async function translate(
  word: string,
  language: Language
): Promise<Translation | null> {
  try {
    const response = await requestBackend('/api/translate-word', { word, language });

    debugLog('Translation response status:', response.status);

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
