import React, { useState, useCallback, useMemo } from 'react';
import {
  ArrowLeft,
  Car,
  ChevronRight,
  ChefHat,
  Clapperboard,
  FlaskConical,
  Film,
  Landmark,
  Plane,
  Tag,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useWordRecommendations } from '../hooks/useWordRecommendations';
import { useWordDetails } from '../hooks/useWordDetails';
import { useUpdateUserwords } from '../hooks/useUpdateUserwords';

interface WordCategoriesProps {
  language: string;
  selectedCategory: string | null;
  categories: { category: string; icon: string | null }[];
  onSelectCategory: (category: string | null) => void;
  categoriesLoading: boolean;
}

// The API sends no usable icons (file_manager.py), so they are picked here.
const CATEGORY_ICONS: Record<string, LucideIcon> = {
  Documentaries: Film,
  Entertainment: Clapperboard,
  Cooking: ChefHat,
  Travel: Plane,
  Politics: Landmark,
  Science: FlaskConical,
  Cars: Car,
};

const SkeletonRows = ({ count }: { count: number }) => (
  <div className="divide-y divide-gray-100" aria-label="Loading">
    {Array.from({ length: count }, (_, i) => (
      <div key={i} className="flex items-center gap-6 py-3 pl-8">
        <span className="h-3 w-24 animate-pulse rounded bg-gray-100" />
        <span className="h-3 w-36 animate-pulse rounded bg-gray-100" />
      </div>
    ))}
  </div>
);

const WordCategories: React.FC<WordCategoriesProps> = ({
  selectedCategory,
  categories,
  onSelectCategory,
  categoriesLoading,
}) => {
  const [selectedWords, setSelectedWords] = useState<number[]>([]);
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(null);
  const [addedIds, setAddedIds] = useState<number[]>([]);

  const { recommendations, isLoading: recommendationsLoading, refreshRecommendations } = useWordRecommendations(selectedCategory);
  const { words: wordDetails, ready: detailsReady } = useWordDetails(recommendations?.word_ids || []);
  const { addWordsToUserwords } = useUpdateUserwords();

  // Share of the topic's videos each word appears in, keyed by word so it
  // stays right after rows are filtered out.
  const coverageById = useMemo(
    () =>
      new Map(
        (recommendations?.word_ids ?? []).map((id, i) => [
          id,
          { share: recommendations!.improvements[i] ?? 0, videos: recommendations!.frequencies[i] ?? 0 },
        ]),
      ),
    [recommendations],
  );
  const totalVideos = recommendations?.total_videos ?? 0;

  // Words not added yet, and not marked invalid by the validation pipeline.
  // Word details come back in database order, so restore the API's ranking.
  const displayedWords = useMemo(() => {
    const rank = new Map((recommendations?.word_ids ?? []).map((id, i) => [id, i]));
    return wordDetails
      .filter((w) => !addedIds.includes(w.word_id) && w.status !== 'invalid')
      .sort((a, b) => (rank.get(a.word_id) ?? Infinity) - (rank.get(b.word_id) ?? Infinity));
  }, [wordDetails, addedIds, recommendations]);

  const toggleWordSelection = useCallback((id: number) => {
    setSelectedWords((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }, []);

  const handleWordClick = (e: React.MouseEvent, index: number, wordId: number) => {
    if (e.shiftKey && lastSelectedIndex !== null) {
      e.preventDefault();
      const range = displayedWords
        .slice(Math.min(index, lastSelectedIndex), Math.max(index, lastSelectedIndex) + 1)
        .map((w) => w.word_id);
      setSelectedWords((prev) => Array.from(new Set([...prev, ...range])));
    } else {
      toggleWordSelection(wordId);
      setLastSelectedIndex(index);
    }
  };

  const handleAddToUserwords = async () => {
    try {
      await addWordsToUserwords(selectedWords, `Frequent Words: ${selectedCategory}`);
      setAddedIds((prev) => [...prev, ...selectedWords]);
      setSelectedWords([]);
      refreshRecommendations();
    } catch (err) {
      console.error('Error adding words:', err);
    }
  };

  if (!selectedCategory) {
    return (
      <div>
        <p className="mb-4 text-sm text-gray-500">
          Pick a topic to see the words that come up most in its videos, ordered by how many of its videos they appear in.
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {categoriesLoading
            ? Array.from({ length: 6 }, (_, i) => <div key={i} className="h-[52px] animate-pulse rounded-lg bg-gray-100" />)
            : categories.map(({ category }) => {
                const Icon = CATEGORY_ICONS[category] ?? Tag;
                return (
                  <button
                    key={category}
                    onClick={() => onSelectCategory(category)}
                    className="group flex items-center gap-3 rounded-lg border border-gray-200 px-3 py-2.5 text-left text-sm font-medium text-gray-800 transition-colors hover:border-gray-300 hover:bg-gray-50"
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-indigo-50 text-indigo-600">
                      <Icon size={16} />
                    </span>
                    <span className="min-w-0 flex-1 truncate">{category}</span>
                    <ChevronRight size={16} className="shrink-0 text-gray-300 transition-colors group-hover:text-gray-500" />
                  </button>
                );
              })}
        </div>
      </div>
    );
  }

  const allSelected = displayedWords.length > 0 && selectedWords.length === displayedWords.length;

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <button
          onClick={() => onSelectCategory(null)}
          className="-ml-1.5 rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-900"
          aria-label="All topics"
          title="All topics"
        >
          <ArrowLeft size={16} />
        </button>
        <h2 className="font-semibold text-gray-900">{selectedCategory}</h2>
        {totalVideos > 0 && (
          <span className="text-sm tabular-nums text-gray-400">
            {totalVideos.toLocaleString()} {totalVideos === 1 ? 'video' : 'videos'}
          </span>
        )}
        {displayedWords.length > 0 && (
          <button
            onClick={() => setSelectedWords(allSelected ? [] : displayedWords.map((w) => w.word_id))}
            className="ml-auto shrink-0 text-sm text-gray-500 hover:text-gray-900"
          >
            {allSelected ? 'Clear selection' : 'Select all'}
          </button>
        )}
      </div>

      {(recommendationsLoading || !detailsReady) && displayedWords.length === 0 ? (
        <SkeletonRows count={8} />
      ) : displayedWords.length === 0 ? (
        <p className="py-10 text-center text-sm text-gray-500">You already know the common words for this topic.</p>
      ) : (
        <table className="w-full table-fixed" onMouseDown={(e) => e.shiftKey && e.preventDefault()}>
          <colgroup>
            <col className="w-8" />
            <col className="w-[30%]" />
            <col />
            <col className="w-28" />
          </colgroup>
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs font-medium text-gray-400">
              <th />
              <th className="pb-2 font-medium">Word</th>
              <th className="pb-2 font-medium">Meaning</th>
              <th className="pb-2 text-right font-medium">In % of videos</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 text-sm">
            {displayedWords.map((word, index) => {
              const selected = selectedWords.includes(word.word_id);
              const coverage = coverageById.get(word.word_id);
              return (
                <tr
                  key={word.word_id}
                  className={`group cursor-pointer ${selected ? 'bg-indigo-50/60' : 'hover:bg-gray-50'}`}
                  onClick={(e) => handleWordClick(e, index, word.word_id)}
                >
                  <td className="py-2 pl-1">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => toggleWordSelection(word.word_id)}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Select ${word.word}`}
                      className={`h-3.5 w-3.5 text-indigo-600 ${selectedWords.length ? '' : 'opacity-0 group-hover:opacity-100'}`}
                    />
                  </td>
                  <td className="truncate py-2 pr-4 font-medium text-gray-900">{word.word}</td>
                  <td className="truncate py-2 pr-4 text-gray-500">{word.translation}</td>
                  <td
                    className="py-2 pr-1 text-right tabular-nums text-gray-500"
                    title={coverage && totalVideos ? `Appears in ${coverage.videos} of ${totalVideos} videos` : undefined}
                  >
                    {Math.round((coverage?.share ?? 0) * 100)}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {selectedWords.length > 0 && (
        <div className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full bg-gray-900 py-1.5 pl-4 pr-1.5 text-sm text-white shadow-lg">
          <span className="mr-2 tabular-nums">{selectedWords.length} selected</span>
          <button className="rounded-full bg-white px-3 py-1 font-medium text-gray-900 hover:bg-gray-100" onClick={handleAddToUserwords}>
            Add to practice
          </button>
          <button className="rounded-full p-1.5 text-gray-400 hover:text-white" onClick={() => setSelectedWords([])} aria-label="Clear selection">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
};

export default WordCategories;
