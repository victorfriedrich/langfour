import { useContext, useEffect, useState } from 'react';
import { UserContext } from '@/context/UserContext';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// The API's grammar.py payloads (GrammarBook, Lesson).
export type ConceptState = 'not yet' | 'studied' | 'fresh' | 'fading';
export type ChapterStatus = 'not started' | 'started' | 'done';

export interface BookChapter {
  id: string;
  number: number;
  level: string;
  title: string;
  description: string;
  status: ChapterStatus;
  concepts: { id: string; title: string; state: ConceptState }[];
}

/** A chapter worth revisiting and its rules that slip often. */
export interface WorthRevisiting {
  chapter: string;
  concepts: string[];
}

export interface ChapterRef {
  id: string;
  number: number;
  title: string;
}

export interface LessonRef {
  id: string;
  title: string;
  chapter: ChapterRef;
}

export interface LessonConcept {
  id: string;
  title: string;
  description: string;
  image: string | null;
  state: ConceptState;
  difficulty: 'easy' | 'medium' | 'hard';
  mode: 'productive' | 'receptive';
  variety: 'spain' | 'latam' | null;
  chunk: boolean;
  pitfall: string | null;
  later: LessonRef[];
  see: LessonRef[];
  used: number;
  mistakes: number;
  last_used_at: string | null;
  refresh_at: string | null;
  revisit?: boolean; // one of the rules its chapter is worth revisiting for
}

export interface Lesson {
  id: string;
  number: number;
  level: string;
  title: string;
  description: string;
  status: ChapterStatus;
  started_at: string | null;
  finished_at: string | null;
  continues: ChapterRef | null;
  previous: ChapterRef | null;
  next: ChapterRef | null;
  concepts: LessonConcept[];
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

/** Every chapter of the grammar book with the user's progress; null while
 *  loading. Also the chapters worth revisiting, best first. */
export const useGrammarBook = (language: string | undefined) => {
  const { fetchWithAuth } = useContext(UserContext);
  const [chapters, setChapters] = useState<BookChapter[] | null>(null);
  const [worthRevisiting, setWorthRevisiting] = useState<WorthRevisiting[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!language) return;
    let cancelled = false;
    setChapters(null);
    fetchWithAuth(`${API_URL}/api/grammar?language=${language}`)
      .then((r) => readJson<{ chapters: BookChapter[]; worth_revisiting?: WorthRevisiting[] }>(r))
      .then((book) => {
        if (cancelled) return;
        setChapters(book.chapters);
        setWorthRevisiting(book.worth_revisiting ?? []);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load grammar'));
    return () => {
      cancelled = true;
    };
  }, [language, fetchWithAuth]);

  return { chapters, worthRevisiting, error };
};

/** One chapter in full. */
export const useLesson = (language: string | undefined, chapterId: string) => {
  const { fetchWithAuth } = useContext(UserContext);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const url = `${API_URL}/api/grammar/chapters/${encodeURIComponent(chapterId)}?language=${language}`;

  useEffect(() => {
    if (!language) return;
    let cancelled = false;
    setLesson(null);
    setError(null);
    fetchWithAuth(url)
      .then((r) => readJson<Lesson>(r))
      .then((l) => !cancelled && setLesson(l))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load the chapter'));
    return () => {
      cancelled = true;
    };
  }, [url, language, fetchWithAuth]);

  return { lesson, error };
};
