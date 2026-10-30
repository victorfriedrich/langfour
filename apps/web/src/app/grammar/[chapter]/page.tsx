"use client";

import React, { useContext } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { UserContext } from "@/context/UserContext";
import ProtectedRoute from "../../components/ProtectedRoute";
import { useLesson, type ChapterRef, type LessonConcept, type LessonRef } from "../../hooks/useGrammar";
import { ConceptStrip, LEVEL_NAMES, Legend, STATES, chapterSlug, countStates } from "../grammarUi";

const DAY_MS = 86_400_000;

function inDays(iso: string) {
  const days = Math.round((Date.parse(iso) - Date.now()) / DAY_MS);
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

const dateLabel = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

const VARIETY: Record<string, string> = { spain: "Spain only", latam: "Latin America only" };

/** The mistake learners typically make with the rule, as the curriculum
 *  states it ("Soy un profesor → Soy profesor"). */
function Pitfall({ text }: { text: string }) {
  return (
    <p className="mt-1.5 text-gray-500">
      Common mistake: <span className="text-gray-700">{text}</span>
    </p>
  );
}

function Refs({ label, refs, chapterId }: { label: string; refs: LessonRef[]; chapterId: string }) {
  if (refs.length === 0) return null;
  return (
    <p className="mt-1.5 text-gray-500">
      {label}{" "}
      {refs.map((r, i) => (
        <React.Fragment key={r.id}>
          {i > 0 && ", "}
          <Link href={`/grammar/${chapterSlug(r.chapter.id)}`} className="text-gray-700 underline decoration-gray-300 underline-offset-2 hover:decoration-gray-500">
            {r.title}
          </Link>
          {r.chapter.id !== chapterId && <span className="text-gray-400"> (chapter {r.chapter.number})</span>}
        </React.Fragment>
      ))}
    </p>
  );
}

function Usage({ concept }: { concept: LessonConcept }) {
  const parts: string[] = [];
  if (concept.used > 0) {
    parts.push(`Used ${concept.used} ${concept.used === 1 ? "time" : "times"}`);
    if (concept.mistakes > 0) parts.push(`${concept.mistakes} ${concept.mistakes === 1 ? "mistake" : "mistakes"}`);
  }
  if (concept.state === "fading") parts.push("due for review in your next chats");
  else if (concept.state === "fresh" && concept.refresh_at) parts.push(`next review ${inDays(concept.refresh_at)}`);
  if (parts.length === 0) return null;
  return <p className="mt-1.5 text-xs text-gray-400">{parts.join(" · ")}</p>;
}

function Rule({ concept, language, chapterId }: { concept: LessonConcept; language: string; chapterId: string }) {
  const state = STATES[concept.state];
  const tags = [
    concept.variety && VARIETY[concept.variety],
    concept.mode === "receptive" && "Recognise only",
    concept.chunk && "Fixed phrase",
  ].filter(Boolean) as string[];

  return (
    <li className="flex gap-4 py-4 text-sm">
      {concept.image && (
        // A symbolic picture per rule, from apps/web/public/grammar/<language>/.
        <img
          src={`/grammar/${language}/${concept.image}`}
          alt=""
          className="h-14 w-14 shrink-0 rounded-lg bg-gray-50 object-contain sm:h-16 sm:w-16"
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h3 className="font-medium text-gray-900">{concept.title}</h3>
          <span className="inline-flex shrink-0 cursor-help items-center gap-1.5 text-xs text-gray-400" title={state.hint}>
            {state.label}
            <i className="h-2 w-2" style={{ backgroundColor: state.color }} />
          </span>
        </div>
        {tags.length > 0 && <p className="mt-0.5 text-xs text-gray-500">{tags.join(" · ")}</p>}
        <p className="mt-1 whitespace-pre-line leading-relaxed text-gray-600">{concept.description}</p>
        {concept.pitfall && <Pitfall text={concept.pitfall} />}
        <Refs label="More on this later:" refs={concept.later} chapterId={chapterId} />
        <Refs label="See also:" refs={concept.see} chapterId={chapterId} />
        <Usage concept={concept} />
      </div>
    </li>
  );
}

function Neighbour({ chapter, direction }: { chapter: ChapterRef | null; direction: "previous" | "next" }) {
  if (!chapter) return <span />;
  const next = direction === "next";
  return (
    <Link
      href={`/grammar/${chapterSlug(chapter.id)}`}
      className={`group flex min-w-0 flex-col gap-0.5 ${next ? "items-end text-right" : ""}`}
    >
      <span className="inline-flex items-center gap-1 text-xs text-gray-400">
        {!next && <ArrowLeft size={12} />}
        Chapter {chapter.number}
        {next && <ArrowRight size={12} />}
      </span>
      <span className="truncate text-sm font-medium text-gray-700 group-hover:text-gray-900">{chapter.title}</span>
    </Link>
  );
}

const LessonPage = () => {
  const { chapter: slug } = useParams<{ chapter: string }>();
  const { language } = useContext(UserContext);
  const chapterId = `${language?.code ?? "es"}.${slug}`;
  const { lesson, error } = useLesson(language?.code, chapterId);

  const states = lesson?.concepts.map((c) => c.state) ?? [];
  const counts = countStates(states);

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-white">
        <div className="max-w-3xl px-4 py-10 sm:px-8">
          <Link href="/grammar" className="mb-4 inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800">
            <ArrowLeft size={14} /> Grammar
          </Link>

          {error && !lesson ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : !lesson ? (
            <div aria-label="Loading" className="space-y-3">
              <div className="h-8 w-48 animate-pulse rounded bg-gray-100" />
              <div className="h-4 w-80 animate-pulse rounded bg-gray-100" />
              <div className="mt-8 h-28 animate-pulse rounded bg-gray-50" />
              <div className="h-28 animate-pulse rounded bg-gray-50" />
            </div>
          ) : (
            <>
              <header className="mb-6">
                <h1 className="text-2xl font-semibold text-gray-900">{lesson.title}</h1>
                <p className="mt-1 text-sm text-gray-500">
                  {lesson.level.toUpperCase()} {LEVEL_NAMES[lesson.level]} · Chapter {lesson.number}
                  {lesson.continues && (
                    <>
                      {" "}· builds on{" "}
                      <Link
                        href={`/grammar/${chapterSlug(lesson.continues.id)}`}
                        className="text-gray-700 underline decoration-gray-300 underline-offset-2 hover:decoration-gray-500"
                      >
                        {lesson.continues.title}
                      </Link>
                    </>
                  )}
                  {lesson.status === "started" && " · in progress"}
                  {lesson.status === "done" && (lesson.finished_at ? ` · done ${dateLabel(lesson.finished_at)}` : " · done")}
                </p>
                <p className="mt-3 text-gray-700">{lesson.description}</p>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
                  <ConceptStrip states={states} size="md" />
                  <Legend counts={counts} />
                </div>
              </header>

              <section>
                <h2 className="flex items-baseline gap-2 border-b border-gray-100 pb-1.5 text-sm font-semibold text-gray-900">
                  Rules <span className="font-normal tabular-nums text-gray-400">{lesson.concepts.length}</span>
                </h2>
                <ul className="divide-y divide-gray-100">
                  {lesson.concepts.map((c) => (
                    <Rule key={c.id} concept={c} language={language?.code ?? "es"} chapterId={lesson.id} />
                  ))}
                </ul>
              </section>

              <nav className="mt-4 grid grid-cols-2 gap-6 border-t border-gray-100 pt-4">
                <Neighbour chapter={lesson.previous} direction="previous" />
                <Neighbour chapter={lesson.next} direction="next" />
              </nav>
            </>
          )}
        </div>
      </div>
    </ProtectedRoute>
  );
};

export default LessonPage;
