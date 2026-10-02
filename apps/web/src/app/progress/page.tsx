"use client";

import React, { useContext, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Search } from "lucide-react";

import { supabase } from "@/lib/supabaseclient";
import { UserContext } from "@/context/UserContext";
import { useCategories } from "../hooks/useCategories";
import ProtectedRoute from "../components/ProtectedRoute";
import KnownWords from "../components/KnownWords";
import WordCategories from "../components/WordCategories";

type View = "known" | "add";

/** How many words Langfour counts as known (sql/known_words.sql): the ones
 *  you marked known, plus the ones your reviews show you have learned. */
function useKnownSummary(languageCode: string | undefined) {
  const [summary, setSummary] = useState<{ declared: number; from_reviews: number } | null>(null);
  useEffect(() => {
    if (!languageCode) return;
    let cancelled = false;
    supabase.rpc("known_words_summary", { language_filter: languageCode }).then(({ data, error }) => {
      if (cancelled) return;
      if (error) console.error("Could not load known words:", error);
      setSummary(data?.[0] ?? { declared: 0, from_reviews: 0 });
    });
    return () => {
      cancelled = true;
    };
  }, [languageCode]);
  return summary;
}

const VocabularyPage = () => {
  const languageCode = useContext(UserContext).language?.code;
  const summary = useKnownSummary(languageCode);
  const [view, setView] = useState<View>("known");
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  const { categories, isLoading: categoriesLoading } = useCategories("es");
  const filteredCategories = useMemo(
    () => categories.filter((c) => c.category !== "Unknown" && c.category !== "Failed"),
    [categories],
  );

  useEffect(() => {
    const handler = setTimeout(() => setDebouncedSearch(searchTerm), 320);
    return () => clearTimeout(handler);
  }, [searchTerm]);

  const switchView = (next: View) => {
    setView(next);
    setSelectedCategory(null);
    setSearchTerm("");
  };

  const tab = (active: boolean) =>
    `-mb-px border-b-2 px-1 pb-3 text-sm font-medium ${
      active ? "border-indigo-600 text-gray-900" : "border-transparent text-gray-500 hover:text-gray-800"
    }`;

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-white">
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <h1 className="mb-8 text-2xl font-semibold text-gray-900">Vocabulary</h1>

          <section className="mb-8">
            {summary ? (
              <>
                <div className="flex items-baseline gap-2.5">
                  <span className="text-5xl font-bold tracking-tight tabular-nums text-gray-900">
                    {(summary.declared + summary.from_reviews).toLocaleString()}
                  </span>
                  <span className="text-gray-600">words you know</span>
                </div>
                {/* The same marks as the rows below, so the list reads as the breakdown of this number. */}
                <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-500">
                  <span className="inline-flex items-center gap-1.5">
                    <i className="h-1.5 w-1.5 rounded-full bg-gray-300" />
                    <b className="font-semibold tabular-nums text-gray-900">{summary.declared.toLocaleString()}</b> marked as known
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <i className="h-1.5 w-1.5 rounded-full bg-indigo-600" />
                    <b className="font-semibold tabular-nums text-gray-900">{summary.from_reviews.toLocaleString()}</b> learned in your reviews
                  </span>
                </p>
                <p className="mt-1 text-xs text-gray-400">
                  Words you are still learning are in{" "}
                  <Link href="/vocabulary" className="text-indigo-600 hover:underline">
                    Practice
                  </Link>
                  .
                </p>
              </>
            ) : (
              // Same height as the summary, so nothing below moves when it arrives.
              <div aria-label="Loading">
                <div className="h-12 w-56 animate-pulse rounded bg-gray-100" />
                <div className="mt-3 h-4 w-80 animate-pulse rounded bg-gray-100" />
                <div className="mt-2 h-3 w-60 animate-pulse rounded bg-gray-100" />
              </div>
            )}
          </section>

          <section>
            <div className="mb-4 flex flex-wrap items-end gap-6 border-b border-gray-100">
              <button className={tab(view === "known")} onClick={() => switchView("known")}>
                Known words
              </button>
              <button className={tab(view === "add")} onClick={() => switchView("add")}>
                Add common words
              </button>
              <Link href="/import" className={`${tab(false)} inline-flex items-center gap-1`}>
                Import <ArrowUpRight size={14} />
              </Link>
              {view === "known" && (
                <label className="relative mb-2 ml-auto">
                  <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search"
                    className="w-48 rounded-lg border border-gray-200 py-1.5 pl-8 pr-3 text-sm placeholder:text-gray-400 focus:border-gray-400 focus:outline-none"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                  />
                </label>
              )}
            </div>

            {view === "known" ? (
              <KnownWords searchTerm={debouncedSearch} />
            ) : (
              <WordCategories
                key={selectedCategory ?? ""} // a fresh selection per topic
                language="es"
                selectedCategory={selectedCategory}
                categories={filteredCategories}
                onSelectCategory={setSelectedCategory}
                categoriesLoading={categoriesLoading}
              />
            )}
          </section>
        </div>
      </div>
    </ProtectedRoute>
  );
};

export default VocabularyPage;
