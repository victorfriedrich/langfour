"""One language's transcript corpus, as a single object.

Row i of the count matrix is the video in filenames[i], with categories[i],
titles[i], creators[i] and lengths[i]. Those used to be ten separate dicts on
the Recommender, filled one at a time, and every caller indexed them on its
own, so nothing checked that they lined up and nothing could replace them
together. Here they are built in one place, checked once, and never changed:
a newer corpus is a new LanguageIndex, so a reader holding an index sees one
consistent corpus for as long as it holds it. Swapping one into the
Recommender is not a single assignment: the hidden-video set (quality filter
plus dropped channels' videos) is computed from the indexes once at boot and
would have to be recomputed with them.

Readers take the index once per request (Recommender.index) and pass it on,
rather than going back to the recommender for each array.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from scipy.sparse import csr_matrix

TRANSCRIPT_SUFFIX = "_processed.json"


def video_id_of(filename: str) -> str:
    """'abc_processed.json' -> 'abc'."""
    return filename.replace(TRANSCRIPT_SUFFIX, "")


@dataclass(frozen=True, eq=False)
class LanguageIndex:
    language: str
    filenames: tuple[str, ...]
    video_ids: tuple[str, ...]
    categories: tuple[str, ...]
    titles: tuple[str, ...]
    creators: tuple[str, ...]          # '' when unknown
    lengths: tuple[int | None, ...]    # seconds, None when unknown
    counts: csr_matrix                 # cell = times the word is spoken
    presence: csr_matrix               # same sparsity, cell = 1
    spoken: np.ndarray                 # words spoken per row
    distinct: np.ndarray               # distinct words per row
    rows: Mapping[str, int]            # video id -> row

    @classmethod
    def build(
        cls,
        language: str,
        filenames: Sequence[str],
        counts: csr_matrix,
        categories: Sequence[str],
        titles: Sequence[str],
        creators: Sequence[str] | None = None,
        lengths: Sequence[int | None] | None = None,
    ) -> LanguageIndex:
        """Check that every column has a value per matrix row, and derive the
        rest. The presence view shares the matrix's index arrays and adds one
        byte per cell, so distinct-word counts ("N new", videos per word) cost
        ~5 MB rather than a second matrix."""
        counts = counts.tocsr()
        n = counts.shape[0]
        creators = [""] * n if creators is None else creators
        lengths = [None] * n if lengths is None else lengths
        columns = {"filenames": filenames, "categories": categories, "titles": titles,
                   "creators": creators, "lengths": lengths}
        wrong = {name: len(values) for name, values in columns.items() if len(values) != n}
        if wrong:
            raise ValueError(f"{language}: {n} matrix rows but {wrong}")

        video_ids = tuple(video_id_of(f) for f in filenames)
        rows = {video_id: row for row, video_id in enumerate(video_ids)}
        if len(rows) != n:
            raise ValueError(f"{language}: {n - len(rows)} video ids appear twice")
        presence = csr_matrix(
            (np.ones(counts.nnz, dtype=np.int8), counts.indices, counts.indptr),
            shape=counts.shape,
        )
        spoken = np.asarray(counts.sum(axis=1)).ravel()
        distinct = np.diff(counts.indptr)
        # Read-only, so no caller can change a corpus other requests are reading.
        # presence may or may not share counts' index arrays, so freeze both sets.
        for array in (counts.data, counts.indices, counts.indptr,
                      presence.data, presence.indices, presence.indptr, spoken, distinct):
            array.flags.writeable = False
        return cls(
            language=language,
            filenames=tuple(filenames),
            video_ids=video_ids,
            categories=tuple(categories),
            titles=tuple(titles),
            creators=tuple(creators),
            lengths=tuple(lengths),
            counts=counts,
            presence=presence,
            spoken=spoken,
            distinct=distinct,
            rows=MappingProxyType(rows),
        )

    def __len__(self) -> int:
        return self.counts.shape[0]

    @property
    def width(self) -> int:
        """Columns: one per dictionary id up to the largest in the corpus."""
        return self.counts.shape[1]

    def word_vector(self, word_ids: Iterable[int], dtype=np.int32) -> np.ndarray:
        """1 at each of `word_ids` that has a column, 0 elsewhere."""
        vector = np.zeros(self.width, dtype=dtype)
        valid = [w for w in word_ids if 0 <= w < self.width]
        if valid:
            vector[valid] = 1
        return vector

    def score(
        self,
        word_ids: Iterable[int],
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
        counts, presence = self.counts, self.presence
        spoken, distinct_words = self.spoken, self.distinct
        if rows is not None:
            counts, presence = counts[rows], presence[rows]
            spoken, distinct_words = spoken[rows], distinct_words[rows]
        # int32: the products are sums of counts, far past int8 and int16.
        vector = self.word_vector(word_ids)

        known_spoken = counts.dot(vector)
        ratios = np.divide(
            known_spoken,
            spoken,
            out=np.zeros(counts.shape[0], dtype=float),
            where=spoken != 0,
        )
        if not distinct:
            return ratios, None, None
        known_distinct = presence.dot(vector).astype(np.int32)
        return ratios, distinct_words - known_distinct, known_distinct
