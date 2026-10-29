"use client";

import React, { useContext, useMemo } from "react";
import Link from "next/link";
import { Check } from "lucide-react";

import { UserContext } from "@/context/UserContext";
import ProtectedRoute from "../components/ProtectedRoute";
import { useGrammarBook, type BookChapter } from "../hooks/useGrammar";
import { ConceptStrip, LEVEL_NAMES, Legend, chapterSlug, countStates } from "./grammarUi";

/** Where the user is in the grammar book. Read only: the chat teaches and
 *  records over MCP; this page shows the progress it leaves behind. */
function ChapterRow({ chapter }: { chapter: BookChapter }) {
  return (
    <li>
      <Link
        href={`/grammar/${chapterSlug(chapter.id)}`}
        className="-mx-2 flex items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-gray-50"
        title={chapter.description}
      >
        <span className="w-5 shrink-0 text-right tabular-nums text-gray-400">{chapter.number}</span>
        <span className="min-w-0 flex-1 truncate">
          <span className={chapter.status === "not started" ? "text-gray-600" : "font-medium text-gray-900"}>
            {chapter.title}
          </span>
          <span className="hidden text-gray-400 sm:inline"> · {chapter.description}</span>
        </span>
        <span className="flex w-24 shrink-0">
          <ConceptStrip states={chapter.concepts.map((c) => c.state)} />
        </span>
        <span className="w-4 shrink-0">
          {chapter.status === "done" && <Check size={14} className="text-indigo-600" aria-label="Done" />}
        </span>
      </Link>
    </li>
  );
}

const GrammarPage = () => {
  const { language } = useContext(UserContext);
  const { chapters, error } = useGrammarBook(language?.code);

  const levels = useMemo(() => {
    const byLevel = new Map<string, BookChapter[]>();
    for (const ch of chapters ?? []) byLevel.set(ch.level, [...(byLevel.get(ch.level) ?? []), ch]);
    return [...byLevel.entries()];
  }, [chapters]);

  const counts = useMemo(() => countStates((chapters ?? []).flatMap((ch) => ch.concepts.map((c) => c.state))), [chapters]);
  const done = chapters?.filter((ch) => ch.status === "done").length ?? 0;
  const started = chapters?.filter((ch) => ch.status === "started").length ?? 0;

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-white">
        <div className="max-w-3xl px-4 py-10 sm:px-8">
          <h1 className="mb-6 text-2xl font-semibold text-gray-900">Grammar</h1>

          {error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : !chapters ? (
            <div aria-label="Loading" className="space-y-2">
              <div className="mb-6 h-4 w-72 animate-pulse rounded bg-gray-100" />
              {Array.from({ length: 10 }, (_, i) => (
                <div key={i} className="h-6 animate-pulse rounded bg-gray-50" />
              ))}
            </div>
          ) : chapters.length === 0 ? (
            <p className="text-gray-500">
              There is no grammar book for {language?.name ?? "this language"} yet. Spanish is the first.
            </p>
          ) : (
            <>
              <section className="mb-8">
                <p className="mb-1 text-sm text-gray-700">
                  <span className="tabular-nums">{done}</span> of <span className="tabular-nums">{chapters.length}</span> chapters
                  done{started > 0 && <>, <span className="tabular-nums">{started}</span> in progress</>}
                </p>
                <Legend counts={counts} />
              </section>

              {levels.map(([level, list]) => (
                <section key={level} className="mb-6">
                  <h2 className="flex items-baseline gap-2 border-b border-gray-100 pb-1.5 text-sm font-semibold text-gray-900">
                    {level.toUpperCase()} {LEVEL_NAMES[level]}
                    <span className="font-normal tabular-nums text-gray-400">
                      {list.filter((c) => c.status === "done").length}/{list.length}
                    </span>
                  </h2>
                  <ul className="py-1">
                    {list.map((ch) => (
                      <ChapterRow key={ch.id} chapter={ch} />
                    ))}
                  </ul>
                </section>
              ))}
            </>
          )}
        </div>
      </div>
    </ProtectedRoute>
  );
};

export default GrammarPage;
