"""How alike two sets of videos are in what they talk about, for Channels at
your level (home.py).

Each video is its binary TF-IDF vector over the recommender's presence matrix
(a word counts once per video, weighted by log(N / videos with the word)),
scaled to length 1. A set of videos (a channel, or the videos a learner
watched from one) is the mean of its videos' vectors, and two sets are as
alike as the cosine of their means. Words in fewer than MIN_DF videos weigh
nothing: they are mostly names, which would make a channel most like itself
and its guests.

Tried on the es corpus on 2026-11-04: the channels most like Enrique Álex
(travel vlogs) were Clavero, HiClavero, César Sar and Jep; most like Marc
Vilas (abandoned places) were Clavero, Jep, Portillo ("72 horas dentro de
Chernobyl") and Kibara. Log counts instead of presence gave the same lists,
and presence is already in memory, so nothing new is held per video: only the
IDF weights, each video's norm and each channel's, cached per matrix.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.sparse import csr_matrix, diags

MIN_DF = 5

_cache: dict[str, tuple[tuple, _Space]] = {}


class _Space:
    def __init__(self, presence: csr_matrix, creators: list[str]):
        n = presence.shape[0]
        df = np.bincount(presence.indices, minlength=presence.shape[1])
        idf = np.log((1 + n) / (1 + df)).astype(np.float32)
        idf[df < MIN_DF] = 0
        self.presence = presence
        self.idf = diags(idf)
        norm = np.sqrt(presence @ (idf.astype(np.float64) ** 2)).astype(np.float32)
        norm[norm == 0] = 1
        self.inv_norm = 1 / norm

        # Every named channel, all its videos: its mean vector's length, so a
        # request needs only each video's dot product with the seeds.
        rows_of: dict[str, list[int]] = defaultdict(list)
        for row, name in enumerate(creators):
            if name:
                rows_of[name].append(row)
        self.channels = {name: i for i, name in enumerate(rows_of)}
        self.pick = self._pick(list(rows_of.values()), n)
        means = (self.pick @ presence @ self.idf).tocsr()
        self.channel_norm = np.sqrt(np.asarray(means.multiply(means).sum(axis=1)).ravel())
        self.channel_norm[self.channel_norm == 0] = 1

    def _pick(self, groups: list[list[int]], n: int) -> csr_matrix:
        """groups x videos: each video's unit vector weighted 1/len(group)."""
        cols = [row for group in groups for row in group]
        weights = np.concatenate([np.full(len(g), 1 / len(g), dtype=np.float32)
                                  for g in groups]) if cols else np.zeros(0, np.float32)
        ptr = np.cumsum([0] + [len(g) for g in groups])
        return csr_matrix((weights * self.inv_norm[cols], cols, ptr), shape=(len(groups), n))

    def seeds(self, groups: list[list[int]]) -> csr_matrix:
        """One unit row per group of matrix rows: the direction of their mean."""
        out = (self._pick(groups, self.presence.shape[0]) @ self.presence @ self.idf).tocsr()
        lengths = np.sqrt(np.asarray(out.multiply(out).sum(axis=1)).ravel())
        lengths[lengths == 0] = 1
        return (diags(1 / lengths) @ out).tocsr()


def space(recommender, language: str) -> _Space:
    presence = recommender.presence[language]
    creators = recommender.creators[language]
    key = (id(presence), presence.shape, presence.nnz, id(creators), len(creators))
    cached = _cache.get(language)
    if cached is None or cached[0] != key:
        cached = (key, _Space(presence, creators))
        _cache[language] = cached
    return cached[1]


def channel_cosines(recommender, language: str, names: list[str],
                    seeds: list[list[int]]) -> np.ndarray:
    """names x seeds: the cosine of each channel (all its videos) with each
    seed (a list of matrix rows). A name the corpus doesn't have scores 0."""
    if not names or not seeds:
        return np.zeros((len(names), len(seeds)), dtype=np.float32)
    s = space(recommender, language)
    # pick carries each video's 1/norm and 1/len(channel), so this is each
    # channel's mean vector dotted with each seed.
    raw = (s.presence @ (s.idf @ s.seeds(seeds).T)).toarray()
    per_channel = (s.pick @ raw) / s.channel_norm[:, None]
    index = [s.channels.get(name) for name in names]
    out = np.zeros((len(names), len(seeds)), dtype=np.float32)
    known = [i for i, j in enumerate(index) if j is not None]
    out[known] = per_channel[[index[i] for i in known]]
    return out
