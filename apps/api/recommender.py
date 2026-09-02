import os
import json
from scipy.sparse import csr_matrix, lil_matrix, save_npz, load_npz
import numpy as np
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import List, Dict, Any
from file_manager import load_documents
from languages import require_code
import time
import tracemalloc

load_dotenv()

class Recommender:
    def __init__(self, base_folder: str):
        tracemalloc.start()
        """
        Initialize the Recommender by preparing structures for multiple languages.
        Documents are now stored as lists of word IDs (integers) rather than full dictionaries.
        """
        self.base_folder = base_folder  # e.g., 'processed'
        self.languages = [lang for lang in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, lang))]
        print(f"Detected languages: {self.languages}")
        
        # Load blacklist
        blacklisted_files = self._load_blacklist()
        
        # Dictionaries to hold language-specific data
        self.documents = {}
        self.filenames = {}
        self.categories = {}
        self.max_word_ids = {}
        self.matrices = {}
        self.total_words_per_doc = {}
        self.user_known_words_cache = {}
        
        # Supabase
        from supabase_client import supabase as _shared_supabase
        self.supabase: Client = _shared_supabase
        
        self.blacklisted_files = blacklisted_files

        # Load every language at startup so the first user request for any
        # language does not pay the matrix load/build cost. _ensure_language_loaded
        # is still used by request paths as a safe no-op if the language is already
        # initialized.
        for lang in self.languages:
            self._ensure_language_loaded(lang)

        current, peak = tracemalloc.get_traced_memory()
        print(f"Recommender initialized | Current: {current/1024/1024:.2f}MB | Peak: {peak/1024/1024:.2f}MB")
        tracemalloc.stop()
    


    def _try_load_cached_language(self, language: str) -> bool:
        matrix_path = os.path.join(self.base_folder, language, "document_term_matrix.npz")
        meta_path = matrix_path + ".meta.json"
        if not (os.path.exists(matrix_path) and os.path.exists(meta_path)):
            return False

        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)

            filenames = meta.get("filenames")
            categories = meta.get("categories")
            max_word_id = meta.get("max_word_id")
            if not filenames or categories is None or len(filenames) != len(categories):
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
            self.max_word_ids[language] = int(max_word_id or matrix.shape[1] - 1)
            self.matrices[language] = matrix
            self.total_words_per_doc[language] = np.asarray(matrix.sum(axis=1)).ravel()
            self.documents[language] = None
            print(f"Document-term matrix and metadata for '{language}' loaded from disk.")
            return True
        except Exception as exc:
            print(f"Could not load cached matrix metadata for '{language}': {exc}")
            return False

    def _ensure_language_loaded(self, language: str) -> None:
        if language not in self.languages:
            raise ValueError(f"Language '{language}' not supported")
        if language in self.matrices:
            return
        if self._try_load_cached_language(language):
            return

        print(f"Initializing data for language: {language}")
        docs, files, cats = load_documents(os.path.join(self.base_folder, language))
        triple = sorted(zip(files, docs, cats))
        if triple:
            files, docs, cats = map(list, zip(*triple))
        else:
            files, docs, cats = [], [], []

        docs, files, cats = self._filter_blacklisted_files(docs, files, cats, self.blacklisted_files)

        self.filenames[language] = files
        self.categories[language] = cats
        self.max_word_ids[language] = self._determine_max_word_id(docs)
        self.matrices[language] = self._create_document_term_matrix(language, docs)
        self.total_words_per_doc[language] = np.asarray(self.matrices[language].sum(axis=1)).ravel()
        # Keep only the compact sparse representation after startup. Holding both
        # the Python list-of-lists and CSR matrix nearly doubles dataset memory.
        self.documents[language] = None

    def get_categories(self, language: str) -> List[Dict[str, Any]]:
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
        word_ids: List[int],
        language: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return known-word counts and comprehension ratios for every row."""
        self._ensure_language_loaded(language)

        matrix = self.matrices[language]
        total_words = self.total_words_per_doc[language]
        word_vector = np.zeros(matrix.shape[1], dtype=np.int8)
        valid_word_ids = [word_id for word_id in word_ids if 0 <= word_id < matrix.shape[1]]
        if valid_word_ids:
            word_vector[valid_word_ids] = 1

        # int8 accumulation overflows for documents containing more than 127
        # matching words. Keep the explicit upcast even though it is temporary.
        known_words = matrix.dot(word_vector.astype(np.int32)).astype(np.int32)
        ratios = np.divide(
            known_words,
            total_words,
            out=np.zeros_like(known_words, dtype=float),
            where=total_words != 0,
        )
        return known_words, ratios

    def calculate_vocabulary_coverage(
        self,
        word_ids: List[int],
        language: str,
    ) -> Dict[str, float]:
        """Calculate top/bottom coverage from matrix scores only.

        Empty rows are cache artifacts rather than useful videos and are excluded.
        In particular, this prevents legacy ``*.npz.meta.json`` rows from
        affecting the result without consulting any transcript JSON.
        """
        _, ratios = self._score_documents_by_words(word_ids, language)
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

    async def debug_video_recommendation(
            self, 
            user_id: str, 
            video_id: str, 
            language: str = "es"
        ) -> Dict[str, Any]:
            """
            Debug a specific video recommendation calculation
            """
            print(f"\n=== DEBUGGING VIDEO {video_id} ===")
            
            try:
                self._ensure_language_loaded(language)
            except ValueError as exc:
                return {"error": str(exc)}
            
            # Get user data
            user_known_words = await self.get_known_words(user_id)
            known_words_set = set(user_known_words)
            print(f"User has {len(user_known_words)} known words")
            
            # Find the video in our data
            files = self.filenames[language]
            D = self.matrices[language]
            cats = self.categories[language]
            
            video_filename = f"{video_id}_processed.json"
            video_index = None
            
            for i, filename in enumerate(files):
                if filename == video_filename:
                    video_index = i
                    break
            
            if video_index is None:
                print(f"❌ Video {video_id} not found in files list")
                print(f"Looking for filename: {video_filename}")
                print(f"Available files (first 10): {files[:10]}")
                return {"error": f"Video {video_id} not found"}
            
            print(f"✅ Found video at index {video_index}")
            print(f"📁 Filename: {files[video_index]}")
            print(f"🏷️ Category: {cats[video_index]}")
            
            # Get the video's word data from the sparse matrix without keeping
            # all document word lists in memory.
            unique_video_words = set(D[video_index].indices.tolist())
            video_words = unique_video_words
            total_unique_words = len(unique_video_words)
            
            print(f"📝 Video has {len(video_words)} total words")
            print(f"🔤 Video has {total_unique_words} unique words")
            
            # Calculate overlap manually
            known_in_video = unique_video_words & known_words_set
            unknown_in_video = unique_video_words - known_words_set
            
            manual_ratio = len(known_in_video) / total_unique_words if total_unique_words > 0 else 0
            manual_percentage = round(manual_ratio * 100, 2)
            
            print(f"🔍 Manual calculation:")
            print(f"  - Known words in video: {len(known_in_video)}")
            print(f"  - Unknown words in video: {len(unknown_in_video)}")
            print(f"  - Comprehension ratio: {manual_ratio:.4f}")
            print(f"  - Comprehension percentage: {manual_percentage}%")
            
            # Now test with the matrix approach
            print(f"\n🔢 Matrix calculation:")
            D = self.matrices[language]
            matrix_vocab_size = D.shape[1]
            
            # Create user vector
            user_vector = np.zeros(matrix_vocab_size, dtype=np.int8)
            valid_known_words = [word_id for word_id in user_known_words if word_id < matrix_vocab_size]
            
            for word_id in valid_known_words:
                user_vector[word_id] = 1
            
            # Get matrix calculations for this video
            total_words_matrix = D[video_index].sum()
            known_words_matrix = D[video_index].dot(user_vector.astype(np.int32)).astype(np.int32)
            matrix_ratio = known_words_matrix / total_words_matrix if total_words_matrix > 0 else 0
            matrix_percentage = matrix_ratio * 100
            
            print(f"  - Total words (matrix): {total_words_matrix}")
            print(f"  - Known words (matrix): {known_words_matrix}")
            print(f"  - Comprehension ratio: {matrix_ratio}")
            print(f"  - Comprehension percentage: {matrix_percentage}%")
            
            # Load the actual JSON file to check metadata
            file_path = os.path.join(self.base_folder, language, files[video_index])
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    video_data = json.load(file)
                
                print(f"\n📋 Video metadata:")
                print(f"  - Title: {video_data.get('title', 'N/A')}")
                print(f"  - Date: {video_data.get('date', 'N/A')}")
                print(f"  - Source: {video_data.get('source', 'N/A')}")
                
            except Exception as e:
                print(f"❌ Error loading video metadata: {e}")
                video_data = {}
            
            # Check for discrepancies
            print(f"\n🔍 Discrepancy analysis:")
            total_diff = abs(int(total_words_matrix) - total_unique_words)
            known_diff = abs(int(known_words_matrix) - len(known_in_video))
            percentage_diff = abs(matrix_percentage - manual_percentage)
            
            print(f"  - Total words difference: {total_diff}")
            print(f"  - Known words difference: {known_diff}")
            print(f"  - Percentage difference: {percentage_diff}%")
            
            if percentage_diff > 1.0:
                print(f"⚠️  SIGNIFICANT DISCREPANCY DETECTED!")
                
                # Check if there are word IDs that exceed matrix bounds
                out_of_bounds_video = [w for w in video_words if w >= matrix_vocab_size]
                out_of_bounds_user = [w for w in user_known_words if w >= matrix_vocab_size]
                
                if out_of_bounds_video:
                    print(f"  - Video has {len(out_of_bounds_video)} words with IDs >= {matrix_vocab_size}")
                    print(f"  - Sample out-of-bounds video words: {out_of_bounds_video[:10]}")
                
                if out_of_bounds_user:
                    print(f"  - User has {len(out_of_bounds_user)} known words with IDs >= {matrix_vocab_size}")
                    print(f"  - Sample out-of-bounds user words: {out_of_bounds_user[:10]}")
            
            # Sample some words for manual verification
            print(f"\n🔤 Sample word analysis:")
            sample_words = list(unique_video_words)[:10]
            for word_id in sample_words:
                is_known = word_id in known_words_set
                in_matrix = word_id < matrix_vocab_size
                matrix_value = D[video_index, word_id] if in_matrix else "N/A"
                print(f"  Word ID {word_id}: Known={is_known}, InMatrix={in_matrix}, MatrixValue={matrix_value}")
            
            return {
                "video_id": video_id,
                "video_index": video_index,
                "manual_percentage": manual_percentage,
                "matrix_percentage": matrix_percentage,
                "total_words_manual": total_unique_words,
                "total_words_matrix": int(total_words_matrix),
                "known_words_manual": len(known_in_video),
                "known_words_matrix": int(known_words_matrix),
                "percentage_difference": percentage_diff,
                "metadata": video_data
            }
    
    
    def _load_blacklist(self) -> set:
        """Load blacklisted filenames from blacklist.txt"""
        blacklist_path = os.path.join(self.base_folder, 'blacklist.txt')
        blacklisted_files = set()
        
        if os.path.exists(blacklist_path):
            try:
                with open(blacklist_path, 'r', encoding='utf-8') as file:
                    for line in file:
                        filename = line.strip()
                        if filename:  # Skip empty lines
                            blacklisted_files.add(filename)
                print(f"Loaded {len(blacklisted_files)} blacklisted files")
            except Exception as e:
                print(f"Error reading blacklist.txt: {e}")
        else:
            print("No blacklist.txt found - proceeding without blacklist")
        
        return blacklisted_files
    
    def _filter_blacklisted_files(self, documents, filenames, categories, blacklisted_files):
        """Filter out blacklisted files from all data structures"""
        if not blacklisted_files:
            return documents, filenames, categories
        
        filtered_docs = []
        filtered_files = []
        filtered_cats = []
        
        original_count = len(filenames)
        
        for i in range(len(filenames)):
            if filenames[i] not in blacklisted_files:
                filtered_docs.append(documents[i])
                filtered_files.append(filenames[i])
                filtered_cats.append(categories[i])
        
        filtered_count = len(filtered_files)
        blacklisted_count = original_count - filtered_count
        
        print(f"Filtered out {blacklisted_count} blacklisted files ({original_count} -> {filtered_count})")
        
        return filtered_docs, filtered_files, filtered_cats
    
    def _determine_max_word_id(self, documents: List[List[int]]) -> int:
        """
        Determine the maximum word ID across all documents.
        Documents now are lists of integer IDs.
        """
        max_id = 0
        for doc in documents:
            for word_id in doc:
                if word_id is not None:
                    max_id = max(max_id, word_id)
        return max_id
    
    def _create_document_term_matrix(
        self, 
        language: str, 
        documents: List[List[int]]
    ) -> csr_matrix:
        """
        Build (or load) the CSR document-term matrix for one language and
        guarantee that its row order, shape and vocabulary match the current
        dataset.  A tiny *.meta.json* file is stored alongside the *.npz*
        cache so we can validate the relationship on every start-up.
        """
        matrix_path = os.path.join(
            self.base_folder, language, "document_term_matrix.npz"
        )
        meta_path = matrix_path + ".meta.json"

        # ------------------------------------------------------------------
        # 1. Fast path – attempt to load the cached matrix if it is still
        #    valid for the *current* dataset
        # ------------------------------------------------------------------
        if os.path.exists(matrix_path) and os.path.exists(meta_path):
            D = load_npz(matrix_path)

            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)

            # Current dataset facts
            current_max_id = self._determine_max_word_id(documents)
            shape_mismatch = (
                D.shape[0] != len(documents)          # file count changed
            or (D.shape[1] - 1) < current_max_id      # new larger IDs
            or meta.get("filenames") != self.filenames[language]  # order/content drift
            or meta.get("categories") != self.categories[language]
            )

            # Always rebuild when *blacklist.txt* is newer than the cache
            blacklist_path = os.path.join(self.base_folder, "blacklist.txt")
            if os.path.exists(blacklist_path):
                if os.path.getmtime(blacklist_path) > os.path.getmtime(matrix_path):
                    shape_mismatch = True
                    print("Blacklist updated – rebuilding matrix for", language)

            if not shape_mismatch:
                print(f"Document-term matrix for '{language}' loaded from disk.")
                return D

            print(f"Dataset changed – rebuilding matrix for '{language}'")

        # ------------------------------------------------------------------
        # 2. Slow path – build the matrix from scratch
        # ------------------------------------------------------------------
        tracemalloc.start()
        print(f"Creating document-term matrix for '{language}'…")
        start = time.time()

        num_docs     = len(documents)
        max_word_id  = self._determine_max_word_id(documents)
        D            = lil_matrix((num_docs, max_word_id + 1), dtype=np.int8)

        for i, doc in enumerate(documents):
            for wid in doc:
                if wid is not None and wid <= max_word_id:
                    D[i, wid] = 1                       # binary presence
            if (i + 1) % 1000 == 0 or (i + 1) == num_docs:
                print(f"  processed {i + 1}/{num_docs} docs")

        D = D.tocsr()
        print(f"Finished in {time.time() - start:.2f}s — caching to disk")

        # Save NPZ
        save_npz(matrix_path, D)

        # Save manifest for future validation
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "filenames": self.filenames[language],
                    "categories": self.categories[language],
                    "max_word_id": int(max_word_id),
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

        # Debug memory stats
        current, peak = tracemalloc.get_traced_memory()
        print(
            f"Matrix for '{language}' => current {current/1_048_576:.2f} MB | "
            f"peak {peak/1_048_576:.2f} MB"
        )
        tracemalloc.stop()

        return D
    
    async def get_seen_videos(self, user_id: str) -> List[str]:
        try:
            seen_video_ids = set()
            page = 0
            while True:
                response = self.supabase.table("videos_seen").select("video_id").eq("user_id", user_id).range(page*1000, (page+1)*1000-1).execute()
                if not response.data:
                    break
                seen_video_ids.update(word['video_id'] for word in response.data)
                page += 1
            return list(seen_video_ids)
        except Exception as e:
            print(f"Error fetching seen videos from Supabase: {str(e)}")
            return []
    
    async def get_known_words(self, user_id: str) -> List[int]:
        start_time = time.time()
        try:
            known_word_ids = set()
            page = 0
            while True:
                response = self.supabase.table("userwords").select("word_id").eq("user_id", user_id).range(page*1000, (page+1)*1000-1).execute()
                if not response.data:
                    break
                known_word_ids.update(word['word_id'] for word in response.data)
                page += 1

            end_time = time.time()
            print(f"Time taken to fetch known words: {end_time - start_time:.2f} seconds")
            self.user_known_words_cache[user_id] = list(known_word_ids)
            return list(known_word_ids)

        except Exception as e:
            print(f"Error fetching known words from Supabase: {str(e)}")
            return []
        
    async def recommend_videos(
        self, 
        user_id: str, 
        language: str, 
        filter_category: str = None, 
        top_n: int = 150
    ) -> List[Dict[str, Any]]:
        start_time = time.time()
        
        try:
            self._ensure_language_loaded(language)
        except ValueError as exc:
            print(exc)
            return []
        
        user_known_words = await self.get_known_words(user_id)
        seen_videos = await self.get_seen_videos(user_id)
        
        print(f"User has {len(user_known_words)} known words and has seen {len(seen_videos)} videos.")
        
        # Get the document-term matrix and other data
        D = self.matrices[language]  # This is your CSR matrix
        files = self.filenames[language]
        cats = self.categories[language]
        
        # Debug matrix dimensions
        print(f"Matrix shape: {D.shape}, Max word ID: {self.max_word_ids[language]}")
        
        # Create user known words vector with same dimensions as matrix
        matrix_vocab_size = D.shape[1]  # Number of columns in the matrix
        user_vector = np.zeros(matrix_vocab_size, dtype=np.int8)
        
        # Filter out word IDs that are beyond our matrix dimensions
        valid_known_words = [word_id for word_id in user_known_words if word_id < matrix_vocab_size]
        filtered_count = len(user_known_words) - len(valid_known_words)
        
        if filtered_count > 0:
            print(f"Filtered {filtered_count} word IDs that exceed matrix dimensions (matrix has {matrix_vocab_size} columns)")
        
        for word_id in valid_known_words:
            user_vector[word_id] = 1
        
        print(f"Using {len(valid_known_words)} known words out of {len(user_known_words)} total")
        
        # Vectorized operations on the entire matrix
        # Calculate total words per document (row sums)
        total_words_per_doc = self.total_words_per_doc[language]
        
        # Calculate known words per document (matrix-vector multiplication)
        known_words_per_doc = D.dot(user_vector.astype(np.int32)).astype(np.int32)
        
        # Calculate comprehension ratios
        comprehension_ratios = np.divide(
            known_words_per_doc, 
            total_words_per_doc, 
            out=np.zeros_like(known_words_per_doc, dtype=float), 
            where=total_words_per_doc != 0
        )
        
        # Create boolean masks for filtering
        seen_video_ids = set(seen_videos)
        valid_indices = []
        
        # Use matrix dimensions to ensure we don't go out of bounds
        num_docs = D.shape[0]  # Number of rows in the matrix
        num_files = len(files)
        
        if num_docs != num_files:
            print(f"Warning: Matrix has {num_docs} documents but files list has {num_files} entries")
            # Use the smaller of the two to avoid index errors
            max_index = min(num_docs, num_files)
        else:
            max_index = num_docs
        
        for i in range(max_index):
            video_id = files[i].replace("_processed.json", "")
            
            # Skip if already seen
            if video_id in seen_video_ids:
                continue
                
            # Skip if wrong category
            if filter_category and cats[i] != filter_category:
                continue
                
            # Skip if too few words (less than 100 unique words)
            if total_words_per_doc[i] < 100:
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
        
        # Now load JSON metadata only for top candidates
        videos = []
        for doc_index, ratio in top_candidates:
            if len(videos) >= top_n:
                break
                
            try:
                video_id = files[doc_index].replace("_processed.json", "")
                file_path = os.path.join(self.base_folder, language, files[doc_index])
                
                with open(file_path, 'r', encoding='utf-8') as file:
                    data = json.load(file)
                
                # Calculate new words (total - known)
                new_words = total_words_per_doc[doc_index] - known_words_per_doc[doc_index]
                
                video_info = {
                    "id": video_id,
                    "percentUnderstood": round(ratio * 100, 2),
                    "category": cats[doc_index],
                    "title": data.get("title", ""),
                    "source": data.get("source", ""),
                    "date": data.get("date", ""),
                    "newWords": int(new_words)
                }
                
                videos.append(video_info)
                
            except Exception as e:
                print(f"Error loading video data from {file_path}: {e}")
                continue
        
        end_time = time.time()
        print(f"Total recommendation time: {end_time - start_time:.2f} seconds")
        
        return videos
    
    def recommend_words_to_learn(
            self,
            language: str,
            known_word_ids: List[int],
            filter_category: str = None,
            n_words: int = 100
        ) -> List[Dict[str, Any]]:
        self._ensure_language_loaded(language)

        D = self.matrices[language]
        cats = self.categories[language]

        if filter_category is None:
            matrix = D
        else:
            indices = [i for i, cat in enumerate(cats) if cat == filter_category]
            if not indices:
                print(f"No documents found for category: {filter_category}")
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

        # CSR is binary, so document count and frequency are currently the same.
        order = np.lexsort((-doc_counts[candidate_ids], -doc_counts[candidate_ids]))[:n_words]
        total_docs = matrix.shape[0]
        return [
            {
                "word_id": int(word_id),
                "improvement": float(doc_counts[word_id] / total_docs),
                "frequency": int(doc_counts[word_id]),
            }
            for word_id in candidate_ids[order]
        ]

    def get_ordered_words(self, language: str, limit: int = 1000) -> List[int]:
        # Was `language = "spanish"`, discarding the argument entirely.
        language = require_code(language)
        try:
            response = self.supabase.table("words").select("id").eq("language", language).limit(limit).execute()
            return response.data
        except Exception as e:
            print(f"Exception in get_ordered_words: {e}")
            return []
        
    def get_random_words(self, language: str, limit: int = 1000) -> List[int]:
        # Was `language = "spanish"`, discarding the argument entirely -- which
        # is why the ISO migration alone did not fix this RPC despite the RPC
        # itself already taking a code.
        language = require_code(language)
        try:
            response = self.supabase.rpc('get_random_words', {'language_code': language, 'limit_words': limit}).execute()
            print(response)
            ids = [word["id"] for word in response.data]
            print(ids)
            return ids
        except Exception as e:
            print(f"Exception in get_random_words: {e}")
            return []
        
    def recommend_videos_by_words(self, word_ids: List[int], language: str, filter_category: str = None, top_n: int = 60) -> List[Dict[str, Any]]:
        start_time = time.time()

        try:
            known_words_per_doc, ratios = self._score_documents_by_words(word_ids, language)
        except ValueError as exc:
            print(exc)
            return []

        D = self.matrices[language]
        files = self.filenames[language]
        cats = self.categories[language]
        total_words_per_doc = self.total_words_per_doc[language]

        valid_indices = []
        for doc_index in range(min(D.shape[0], len(files))):
            if filter_category and cats[doc_index] != filter_category:
                continue
            valid_indices.append(doc_index)

        valid_indices.sort(key=lambda i: ratios[i], reverse=True)
        videos = []
        for doc_index in valid_indices[:top_n]:
            try:
                video_id = files[doc_index].replace("_processed.json", "")
                file_path = os.path.join(self.base_folder, language, files[doc_index])
                with open(file_path, 'r', encoding='utf-8') as file:
                    data = json.load(file)

                known_words = int(known_words_per_doc[doc_index])
                total_words = int(total_words_per_doc[doc_index])
                videos.append({
                    "id": video_id,
                    "percentUnderstood": round(float(ratios[doc_index]) * 100, 2),
                    "category": cats[doc_index],
                    "title": data.get("title", ""),
                    "source": data.get("source", ""),
                    "date": data.get("date", ""),
                    "newWords": max(total_words - known_words, 0),
                    "knownWords": known_words,
                })
            except Exception as e:
                print(f"Error loading video data from {file_path}: {e}")

        end_time = time.time()
        print(f"Total recommendation time: {end_time - start_time:.2f} seconds")
        return videos[:top_n]
