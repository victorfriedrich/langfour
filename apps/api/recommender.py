import json
import logging
import os
import time
from typing import Any

import numpy as np
from dotenv import load_dotenv
from scipy.sparse import csr_matrix, load_npz, save_npz
from supabase import Client

from file_manager import Document, load_documents
from languages import require_code

load_dotenv()

logger = logging.getLogger(__name__)

# What a matrix cell holds, written into the .meta.json next to the cached
# .npz. Cells used to be 1 for "word appears", so a percentage was the share of
# *distinct* words known, which falls with video length (rank correlation
# about -0.5) while the share of words heard doesn't. A cache without this
# marker is a binary matrix of the same shape and would load silently.
MATRIX_WEIGHTS = "counts"
# The counts cache has its own name, so code from before counts (a rollback,
# an older checkout sharing the data dir) never loads it as 0/1: it keeps
# reading or rebuilding document_term_matrix.npz.
MATRIX_FILE = "document_term_counts.npz"
# Videos with fewer distinct words are clips; counting repeats would put them
# near 100% for everyone.
MIN_DISTINCT_WORDS = 100
# Rows asked for per user_known_words request; see known_word_ids.
KNOWN_WORDS_PAGE = 50_000

class Recommender:
    def __init__(self, base_folder: str):
        """
        Initialize the Recommender by preparing structures for multiple languages.
        Documents are now stored as lists of word IDs (integers) rather than full dictionaries.
        """
        self.base_folder = base_folder  # e.g., 'processed'
        self.languages = [lang for lang in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, lang))]
        logger.info("Detected languages: %s", self.languages)

        # Load blacklist
        blacklisted_files = self._load_blacklist()
        
        # Dictionaries to hold language-specific data
        self.documents = {}
        self.filenames = {}
        self.categories = {}
        self.titles = {}
        self.max_word_ids = {}
        self.matrices = {}             # cell = times the word is spoken
        self.presence = {}             # same sparsity, cell = 1
        self.total_words_per_doc = {}  # words spoken
        self.distinct_words_per_doc = {}
        self.rows_by_video = {}        # video id -> matrix row

        # Supabase
        from supabase_client import supabase as _shared_supabase
        self.supabase: Client = _shared_supabase
        
        self.blacklisted_files = blacklisted_files
        self.hidden_videos = self._load_hidden_videos()

        # Load every language at startup so the first user request for any
        # language does not pay the matrix load/build cost. _ensure_language_loaded
        # is still used by request paths as a safe no-op if the language is already
        # initialized.
        for lang in self.languages:
            self._ensure_language_loaded(lang)

        # Report the steady-state footprint of what we actually retain. This is
        # the number that governs how much memory the container needs, and it
        # is free to compute -- unlike tracemalloc, which was tracing every
        # allocation during startup purely to print one line.
        matrix_bytes = sum(
            m.data.nbytes + m.indices.nbytes + m.indptr.nbytes
            for m in self.matrices.values()
        ) + sum(p.data.nbytes for p in self.presence.values())
        logger.info(
            "Recommender initialized | %d languages | %d documents | %.1f MB resident matrices",
            len(self.matrices),
            sum(m.shape[0] for m in self.matrices.values()),
            matrix_bytes / 1024 / 1024,
        )



    def _try_load_cached_language(self, language: str) -> bool:
        matrix_path = os.path.join(self.base_folder, language, MATRIX_FILE)
        meta_path = matrix_path + ".meta.json"
        if not (os.path.exists(matrix_path) and os.path.exists(meta_path)):
            return False

        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)

            filenames = meta.get("filenames")
            categories = meta.get("categories")
            titles = meta.get("titles")
            max_word_id = meta.get("max_word_id")
            if meta.get("weights") != MATRIX_WEIGHTS:
                logger.info("Cached matrix for '%s' is binary; rebuilding with counts.", language)
                return False
            if (
                not filenames
                or categories is None
                or titles is None
                or len(filenames) != len(categories)
                or len(filenames) != len(titles)
            ):
                return False

            json_filenames = sorted(
                filename
                for filename in os.listdir(os.path.join(self.base_folder, language))
                if filename.endswith(".json") and filename not in self.blacklisted_files
            )
            if json_filenames != filenames:
                # Existing committed caches may include their .npz.meta.json file as
                # an empty document row. New rebuilds skip metadata files, so accept
                # either shape without requiring binary matrix changes in the PR.
                content_filenames = sorted(
                    filename
                    for filename in json_filenames
                    if not filename.endswith(".npz.meta.json")
                )
                if content_filenames != filenames:
                    return False

            matrix = load_npz(matrix_path)
            if matrix.shape[0] != len(filenames):
                return False
            if max_word_id is not None and (matrix.shape[1] - 1) < int(max_word_id):
                return False

            self.filenames[language] = filenames
            self.categories[language] = categories
            self.titles[language] = titles
            self.max_word_ids[language] = int(max_word_id or matrix.shape[1] - 1)
            self._index_matrix(language, matrix)
            self.documents[language] = None
            logger.info("Document-term matrix and metadata for '%s' loaded from disk.", language)
            return True
        except Exception:
            logger.warning(
                "Could not load cached matrix metadata for '%s'; will rebuild.",
                language, exc_info=True,
            )
            return False

    def _ensure_language_loaded(self, language: str) -> None:
        if language not in self.languages:
            raise ValueError(f"Language '{language}' not supported")
        if language in self.matrices:
            return
        if self._try_load_cached_language(language):
            return

        logger.info("Initializing data for language: %s", language)
        docs, files, cats, titles = load_documents(os.path.join(self.base_folder, language))
        rows = sorted(zip(files, docs, cats, titles, strict=False))
        if rows:
            files, docs, cats, titles = map(list, zip(*rows, strict=False))
        else:
            files, docs, cats, titles = [], [], [], []

        docs, files, cats, titles = self._filter_blacklisted_files(
            docs, files, cats, titles, self.blacklisted_files
        )

        self.filenames[language] = files
        self.categories[language] = cats
        self.titles[language] = titles
        self.max_word_ids[language] = self._determine_max_word_id(docs)
        self._index_matrix(language, self._create_document_term_matrix(language, docs))
        # Keep only the compact sparse representation after startup. Holding both
        # the per-document arrays and the CSR matrix doubles dataset memory.
        self.documents[language] = None

    def _index_matrix(self, language: str, matrix: csr_matrix) -> None:
        """Register a count matrix and what is derived from it.

        The presence view shares the matrix's index arrays and adds one byte
        per cell, so distinct-word counts ("N new", videos per word) cost
        ~5 MB rather than a second matrix."""
        matrix = matrix.tocsr()
        self.matrices[language] = matrix
        self.presence[language] = csr_matrix(
            (np.ones(matrix.nnz, dtype=np.int8), matrix.indices, matrix.indptr),
            shape=matrix.shape,
        )
        self.total_words_per_doc[language] = np.asarray(matrix.sum(axis=1)).ravel()
        self.distinct_words_per_doc[language] = np.diff(matrix.indptr)
        # Callers set filenames first; rows follow their order.
        self.rows_by_video[language] = {
            filename.replace("_processed.json", ""): row
            for row, filename in enumerate(self.filenames.get(language, [])[:matrix.shape[0]])
        }

    def get_categories(self, language: str) -> list[dict[str, Any]]:
        """Return stable category metadata without reopening transcript files."""
        self._ensure_language_loaded(language)
        categories = sorted({
            category
            for category in self.categories[language]
            if category and category != "Unknown"
        })
        return [{"category": category, "icon": None} for category in categories]

    def _score_documents_by_words(
        self,
        word_ids: list[int],
        language: str,
        distinct: bool = True,
        rows: list[int] | None = None,
    ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
        """Per row: the share of words spoken that are in `word_ids`, how many
        distinct words are not, and how many distinct words are.

        The share counts every repeat, which is what a viewer hears; the two
        counts are of distinct words, which is what there is to learn. This is
        the one fit calculation every surface shows. distinct=False skips the
        second product and returns None for both counts. `rows` scores only
        those rows, in that order, rather than the whole matrix."""
        self._ensure_language_loaded(language)

        matrix = self.matrices[language]
        presence = self.presence[language]
        total_words = self.total_words_per_doc[language]
        distinct_words = self.distinct_words_per_doc[language]
        if rows is not None:
            matrix, presence = matrix[rows], presence[rows]
            total_words, distinct_words = total_words[rows], distinct_words[rows]
        # int32: the products are sums of counts, far past int8 and int16.
        word_vector = np.zeros(matrix.shape[1], dtype=np.int32)
        valid_word_ids = [word_id for word_id in word_ids if 0 <= word_id < matrix.shape[1]]
        if valid_word_ids:
            word_vector[valid_word_ids] = 1

        known_spoken = matrix.dot(word_vector)
        ratios = np.divide(
            known_spoken,
            total_words,
            out=np.zeros(matrix.shape[0], dtype=float),
            where=total_words != 0,
        )
        if not distinct:
            return ratios, None, None
        known_distinct = presence.dot(word_vector).astype(np.int32)
        new_distinct = distinct_words - known_distinct
        return ratios, new_distinct, known_distinct

    def calculate_vocabulary_coverage(
        self,
        word_ids: list[int],
        language: str,
    ) -> dict[str, float]:
        """Calculate top/bottom coverage from matrix scores only.

        Empty rows are cache artifacts rather than useful videos and are excluded.
        In particular, this prevents legacy ``*.npz.meta.json`` rows from
        affecting the result without consulting any transcript JSON.
        """
        ratios, _, _ = self._score_documents_by_words(word_ids, language, distinct=False)
        nonempty_rows = self.total_words_per_doc[language] > 0
        percentages = ratios[nonempty_rows] * 100

        if percentages.size == 0:
            return {"top30_avg": 0.0, "bottom30_avg": 0.0}

        percentages.sort()
        count = max(1, int(percentages.size * 0.3))
        return {
            "top30_avg": float(np.mean(percentages[-count:])),
            "bottom30_avg": float(np.mean(percentages[:count])),
        }

    def _load_hidden_videos(self) -> set[str]:
        """Videos video_quality.hidden() rejects: garbled captions, lessons for
        another language, songs, and low-content videos.

        Unlike the blacklist they stay in the matrix -- they only never get
        recommended -- so re-tuning a threshold needs a restart, not a rebuild.
        A failed read recommends everything rather than nothing."""
        import video_quality
        try:
            hidden = video_quality.hidden_ids(self.supabase)
        except Exception:
            logger.warning("Could not load video scores; not filtering", exc_info=True)
            return set()
        logger.info("Hiding %d videos by quality score", len(hidden))
        return hidden

    def _load_blacklist(self) -> set:
        """Load blacklisted filenames from blacklist.txt"""
        blacklist_path = os.path.join(self.base_folder, 'blacklist.txt')
        blacklisted_files = set()
        
        if os.path.exists(blacklist_path):
            try:
                with open(blacklist_path, encoding='utf-8') as file:
                    for line in file:
                        filename = line.strip()
                        if filename:  # Skip empty lines
                            blacklisted_files.add(filename)
                logger.info("Loaded %d blacklisted files", len(blacklisted_files))
            except Exception:
                logger.error("Error reading blacklist.txt", exc_info=True)
        else:
            logger.info("No blacklist.txt found - proceeding without blacklist")
        
        return blacklisted_files
    
    def _filter_blacklisted_files(
        self, documents, filenames, categories, titles, blacklisted_files
    ):
        """Filter out blacklisted files from all data structures"""
        if not blacklisted_files:
            return documents, filenames, categories, titles
        
        filtered_docs = []
        filtered_files = []
        filtered_cats = []
        filtered_titles = []
        
        original_count = len(filenames)
        
        for i in range(len(filenames)):
            if filenames[i] not in blacklisted_files:
                filtered_docs.append(documents[i])
                filtered_files.append(filenames[i])
                filtered_cats.append(categories[i])
                filtered_titles.append(titles[i])
        
        filtered_count = len(filtered_files)
        blacklisted_count = original_count - filtered_count
        
        logger.info(
            "Filtered out %d blacklisted files (%d -> %d)",
            blacklisted_count, original_count, filtered_count,
        )
        
        return filtered_docs, filtered_files, filtered_cats, filtered_titles
    
    def _determine_max_word_id(self, documents: list[Document]) -> int:
        """The largest word id in any document (each document's ids are sorted)."""
        return max((int(ids[-1]) for ids, _ in documents if ids.size), default=0)

    def _write_matrix_metadata(self, language: str, max_word_id: int) -> None:
        meta_path = os.path.join(
            self.base_folder, language, MATRIX_FILE + ".meta.json"
        )
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "filenames": self.filenames[language],
                    "categories": self.categories[language],
                    "titles": self.titles[language],
                    "max_word_id": int(max_word_id),
                    "weights": MATRIX_WEIGHTS,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
    
    def _create_document_term_matrix(
        self, 
        language: str, 
        documents: list[Document]
    ) -> csr_matrix:
        """
        Build (or load) the CSR document-term matrix for one language and
        guarantee that its row order, shape and vocabulary match the current
        dataset.  A tiny *.meta.json* file is stored alongside the *.npz*
        cache so we can validate the relationship on every start-up.
        """
        matrix_path = os.path.join(self.base_folder, language, MATRIX_FILE)
        meta_path = matrix_path + ".meta.json"

        # ------------------------------------------------------------------
        # 1. Fast path – attempt to load the cached matrix if it is still
        #    valid for the *current* dataset
        # ------------------------------------------------------------------
        if os.path.exists(matrix_path) and os.path.exists(meta_path):
            D = load_npz(matrix_path)

            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)

            # Current dataset facts
            current_max_id = self._determine_max_word_id(documents)
            shape_mismatch = (
                D.shape[0] != len(documents)          # file count changed
            or (D.shape[1] - 1) < current_max_id      # new larger IDs
            or meta.get("filenames") != self.filenames[language]  # order/content drift
            or meta.get("categories") != self.categories[language]
            or meta.get("weights") != MATRIX_WEIGHTS              # a binary cache
            )

            # Always rebuild when *blacklist.txt* is newer than the cache
            blacklist_path = os.path.join(self.base_folder, "blacklist.txt")
            if os.path.exists(blacklist_path):
                if os.path.getmtime(blacklist_path) > os.path.getmtime(matrix_path):
                    shape_mismatch = True
                    logger.info("Blacklist updated - rebuilding matrix for %s", language)

            if not shape_mismatch:
                if meta.get("titles") != self.titles[language]:
                    self._write_matrix_metadata(language, current_max_id)
                logger.info("Document-term matrix for '%s' loaded from disk.", language)
                return D

            logger.info("Dataset changed - rebuilding matrix for '%s'", language)

        # ------------------------------------------------------------------
        # 2. Slow path – build the matrix from scratch
        # ------------------------------------------------------------------
        logger.info("Creating document-term matrix for '%s'...", language)
        start = time.time()

        num_docs     = len(documents)
        max_word_id  = self._determine_max_word_id(documents)
        # Times each word is spoken. int16 holds it: the most in one video is
        # 771. Documents arrive as sorted (ids, counts), which is CSR already.
        indptr = np.zeros(num_docs + 1, dtype=np.int64)
        np.cumsum([ids.size for ids, _ in documents], out=indptr[1:])
        indices = np.concatenate([ids for ids, _ in documents] or [np.empty(0, np.int32)])
        counts = np.concatenate([c for _, c in documents] or [np.empty(0, np.int32)])
        D = csr_matrix(
            (np.minimum(counts, np.iinfo(np.int16).max).astype(np.int16), indices, indptr),
            shape=(num_docs, max_word_id + 1),
        )
        logger.info("Finished in %.2fs - caching to disk", time.time() - start)

        # Save NPZ
        save_npz(matrix_path, D)

        self._write_matrix_metadata(language, max_word_id)

        logger.info(
            "Matrix for '%s' => %d x %d, %d nonzeros, %.2f MB resident",
            language, D.shape[0], D.shape[1], D.nnz,
            (D.data.nbytes + D.indices.nbytes + D.indptr.nbytes) / 1_048_576,
        )

        return D
    
    async def get_watched_videos(self, user_id: str) -> list[str]:
        """Videos the user watched (watch_events, rules in watch.py), which
        recommendations leave out. Unmarked ones and ones left under 70% come
        back."""
        from watch import is_watched  # imports the Supabase client, like __init__ does
        try:
            watched: set[str] = set()
            page = 0
            while True:
                response = (self.supabase.table("watch_events")
                            .select("video_id, share, unmarked_at")
                            .eq("user_id", user_id).is_("unmarked_at", "null")
                            .order("id").range(page*1000, (page+1)*1000-1).execute())
                if not response.data:
                    break
                watched.update(r["video_id"] for r in response.data if is_watched(r))
                page += 1
            return list(watched)
        except Exception:
            logger.error("Error fetching watched videos from Supabase", exc_info=True)
            return []

    async def get_known_words(self, user_id: str) -> list[int]:
        """Words the user knows: declared known, or learned in reviews
        (sql/known_words.sql). A word only saved, or still being learned,
        does not count, so it shows up as new in a video."""
        try:
            return self.known_word_ids(user_id)
        except Exception:
            logger.error("Error fetching known words from Supabase", exc_info=True)
            return []

    def known_word_ids(self, user_id: str) -> list[int]:
        """get_known_words without the coroutine, for a worker thread: the
        Supabase client blocks, and on the event loop it would stall every
        other request while the pages come in. It raises when Supabase fails
        rather than answering "no words": the extension keeps fit badges for
        hours, and a page of 0% would stay that long."""
        start_time = time.time()
        known_word_ids = set()
        # Ask for far more than PostgREST's row cap and carry on from what
        # came back, so one or two round trips do whatever the cap is.
        # Fixed pages of 1,000 took five sequential requests (~300 ms) for
        # 4,000 words, which every fit badge batch waited on.
        offset = 0
        while True:
            response = (self.supabase.table("user_known_words").select("word_id")
                        .eq("user_id", user_id).order("word_id")
                        .range(offset, offset + KNOWN_WORDS_PAGE - 1).execute())
            if not response.data:
                break
            known_word_ids.update(word['word_id'] for word in response.data)
            offset += len(response.data)

        logger.debug(
            "Fetched %d known words in %.2fs", len(known_word_ids), time.time() - start_time
        )
        return list(known_word_ids)

    async def get_saved_words(self, user_id: str) -> list[int]:
        """Every word in the user's list, whatever its status. Unlike known
        words these still count as new in a video, but a list of words to add
        must leave them out: adding one again rewrites its learning state."""
        try:
            saved_word_ids = set()
            page = 0
            while True:
                response = (self.supabase.table("userwords").select("word_id")
                            .eq("user_id", user_id).order("word_id")
                            .range(page*1000, (page+1)*1000-1).execute())
                if not response.data:
                    break
                saved_word_ids.update(word['word_id'] for word in response.data)
                page += 1
            return list(saved_word_ids)
        except Exception:
            logger.error("Error fetching saved words from Supabase", exc_info=True)
            return []
        
    async def recommend_videos(
        self, 
        user_id: str, 
        language: str, 
        filter_category: str | None = None, 
        top_n: int = 150
    ) -> list[dict[str, Any]]:
        start_time = time.time()
        
        try:
            self._ensure_language_loaded(language)
        except ValueError:
            logger.warning("recommend_videos: unsupported language %r", language)
            return []

        user_known_words = await self.get_known_words(user_id)
        seen_videos = await self.get_watched_videos(user_id)

        logger.debug(
            "User has %d known words and has seen %d videos.",
            len(user_known_words), len(seen_videos),
        )
        
        # Get the document-term matrix and other data
        D = self.matrices[language]  # This is your CSR matrix
        files = self.filenames[language]
        cats = self.categories[language]
        titles = self.titles[language]
        distinct_words_per_doc = self.distinct_words_per_doc[language]

        comprehension_ratios, new_words_per_doc, _ = self._score_documents_by_words(
            user_known_words, language
        )

        # Create boolean masks for filtering
        seen_video_ids = set(seen_videos)
        valid_indices = []
        
        # Use matrix dimensions to ensure we don't go out of bounds
        num_docs = D.shape[0]  # Number of rows in the matrix
        num_files = len(files)
        
        if num_docs != num_files:
            logger.warning(
                "Matrix has %d documents but files list has %d entries", num_docs, num_files
            )
            # Use the smaller of the two to avoid index errors
            max_index = min(num_docs, num_files)
        else:
            max_index = num_docs
        
        for i in range(max_index):
            video_id = files[i].replace("_processed.json", "")
            
            # Skip if already seen
            if video_id in seen_video_ids:
                continue

            # Skip if the quality scores reject it
            if video_id in self.hidden_videos:
                continue
                
            # Skip if wrong category
            if filter_category and cats[i] != filter_category:
                continue
                
            # Skip if too few words (less than 100 unique words)
            if distinct_words_per_doc[i] < MIN_DISTINCT_WORDS:
                continue
                
            valid_indices.append(i)
        
        if not valid_indices:
            return []
        
        # Get scores for valid documents only
        valid_scores = [(i, comprehension_ratios[i]) for i in valid_indices]
        
        # Sort by comprehension ratio (descending)
        valid_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Take top candidates (more than needed in case some fail to load)
        top_candidates = valid_scores[:min(top_n * 2, len(valid_scores))]
        
        videos = []
        for doc_index, ratio in top_candidates:
            if len(videos) >= top_n:
                break

            videos.append({
                "id": files[doc_index].replace("_processed.json", ""),
                "percentUnderstood": round(float(ratio) * 100, 2),
                "category": cats[doc_index],
                "title": titles[doc_index],
                "newWords": int(new_words_per_doc[doc_index]),
            })

        end_time = time.time()
        logger.debug("Total recommendation time: %.2f seconds", end_time - start_time)

        return videos
    
    def fit_videos(
        self,
        video_ids: list[str],
        word_ids: list[int],
        language: str,
    ) -> dict[str, dict[str, Any]]:
        """How well `word_ids` cover each of `video_ids`, scoring only their
        rows: the thumbnail badges ask for a page of cards at a time.

        Each id gets a status. "scored" carries percentUnderstood (heard
        coverage) and newWords (distinct); "unindexed" means no transcript;
        "hidden" is indexed but never recommended (the quality filter, or a
        clip under MIN_DISTINCT_WORDS), so it gets no number either."""
        self._ensure_language_loaded(language)
        rows_by_video = self.rows_by_video[language]
        distinct_words = self.distinct_words_per_doc[language]

        fits: dict[str, dict[str, Any]] = {}
        scored: list[tuple[str, int]] = []
        for video_id in video_ids:
            row = rows_by_video.get(video_id)
            if row is None:
                fits[video_id] = {"status": "unindexed"}
            elif video_id in self.hidden_videos or distinct_words[row] < MIN_DISTINCT_WORDS:
                fits[video_id] = {"status": "hidden"}
            else:
                scored.append((video_id, row))

        if scored:
            ratios, new_words, _ = self._score_documents_by_words(
                word_ids, language, rows=[row for _, row in scored]
            )
            for index, (video_id, _) in enumerate(scored):
                fits[video_id] = {
                    "status": "scored",
                    "percentUnderstood": round(float(ratios[index]) * 100, 2),
                    "newWords": int(new_words[index]),
                }
        return fits

    def count_documents(self, language: str, filter_category: str | None = None) -> int:
        self._ensure_language_loaded(language)
        cats = self.categories[language]
        if filter_category is None:
            return len(cats)
        return sum(1 for cat in cats if cat == filter_category)

    def recommend_words_to_learn(
            self,
            language: str,
            known_word_ids: list[int],
            filter_category: str | None = None,
            n_words: int = 100
        ) -> list[dict[str, Any]]:
        self._ensure_language_loaded(language)

        # The presence view: a word's rank is how many videos it appears in,
        # not how often it is said in a few of them.
        D = self.presence[language]
        cats = self.categories[language]

        if filter_category is None:
            matrix = D
        else:
            indices = [i for i, cat in enumerate(cats) if cat == filter_category]
            if not indices:
                logger.info("No documents found for category: %s", filter_category)
                return []
            matrix = D[indices]

        if matrix.shape[0] == 0:
            return []

        doc_counts = np.asarray(matrix.sum(axis=0)).ravel()
        known = np.asarray([wid for wid in known_word_ids if 0 <= wid < matrix.shape[1]], dtype=np.int64)
        if known.size:
            doc_counts[known] = 0

        candidate_ids = np.flatnonzero(doc_counts)
        if candidate_ids.size == 0:
            return []

        # Most videos first; ties go to the lower word id, which is the more
        # common word.
        order = np.lexsort((candidate_ids, -doc_counts[candidate_ids]))[:n_words]
        total_docs = matrix.shape[0]
        return [
            {
                "word_id": int(word_id),
                "improvement": float(doc_counts[word_id] / total_docs),
                "frequency": int(doc_counts[word_id]),
            }
            for word_id in candidate_ids[order]
        ]

    def get_ordered_words(self, language: str, limit: int = 1000) -> list[int]:
        # Was `language = "spanish"`, discarding the argument entirely.
        language = require_code(language)
        try:
            response = self.supabase.table("words").select("id").eq("language", language).limit(limit).execute()
            return response.data
        except Exception:
            logger.error("Exception in get_ordered_words", exc_info=True)
            return []
        
    def get_random_words(self, language: str, limit: int = 1000) -> list[int]:
        # Was `language = "spanish"`, discarding the argument entirely -- which
        # is why the ISO migration alone did not fix this RPC despite the RPC
        # itself already taking a code.
        language = require_code(language)
        try:
            response = self.supabase.rpc('get_random_words', {'language_code': language, 'limit_words': limit}).execute()
            ids = [word["id"] for word in response.data]
            logger.debug("get_random_words(%s) -> %d ids", language, len(ids))
            return ids
        except Exception:
            logger.error("Exception in get_random_words", exc_info=True)
            return []
        
    def recommend_videos_by_words(
        self,
        word_ids: list[int],
        language: str,
        filter_category: str | None = None,
        top_n: int = 60,
        rank_by_distinct: bool = False,
        distinct: bool = True,
    ) -> list[dict[str, Any]]:
        """Videos ordered by the share of their speech `word_ids` cover, or,
        with rank_by_distinct (words to learn), by how many different words
        of `word_ids` they contain, so one word said 60 times doesn't win.
        distinct=False leaves out newWords/knownWords and the product behind
        them, for callers that only read percentUnderstood."""
        start_time = time.time()

        try:
            ratios, new_words_per_doc, known_words_per_doc = self._score_documents_by_words(
                word_ids, language, distinct=distinct or rank_by_distinct
            )
        except ValueError:
            logger.warning("recommend_videos_by_words: unsupported language %r", language)
            return []

        D = self.matrices[language]
        files = self.filenames[language]
        cats = self.categories[language]
        titles = self.titles[language]
        distinct_words_per_doc = self.distinct_words_per_doc[language]

        valid_indices = []
        for doc_index in range(min(D.shape[0], len(files))):
            if filter_category and cats[doc_index] != filter_category:
                continue
            if files[doc_index].replace("_processed.json", "") in self.hidden_videos:
                continue
            if distinct_words_per_doc[doc_index] < MIN_DISTINCT_WORDS:
                continue
            valid_indices.append(doc_index)

        if rank_by_distinct:
            valid_indices.sort(key=lambda i: (known_words_per_doc[i], ratios[i]), reverse=True)
        else:
            valid_indices.sort(key=lambda i: ratios[i], reverse=True)
        videos = []
        for doc_index in valid_indices[:top_n]:
            video = {
                "id": files[doc_index].replace("_processed.json", ""),
                "percentUnderstood": round(float(ratios[doc_index]) * 100, 2),
                "category": cats[doc_index],
                "title": titles[doc_index],
            }
            if known_words_per_doc is not None:
                video["newWords"] = int(new_words_per_doc[doc_index])
                video["knownWords"] = int(known_words_per_doc[doc_index])
            videos.append(video)

        end_time = time.time()
        logger.debug("Total recommendation time: %.2f seconds", end_time - start_time)
        return videos[:top_n]
