# Reviewing flagged dictionary roots

Roots the Jev audit could not settle (`words.status = 'flagged'`) get a definite verdict from rules, then from Claude agents running on the Claude plan (not OpenRouter).

## Run it

1. **Prepare.** Writes `auto.tsv` (rule decisions) and `batch_NNN.tsv` (500 roots each, `id<TAB>root<TAB>up to 6 forms`):
   ```bash
   cd apps/api && python3 scripts/review_flagged.py prepare es --out /tmp/review/es
   ```
2. **Review.** For each batch file, one Sonnet subagent (`Agent`, `model: sonnet`) with the prompt below. Run about 6 at a time, 2 batch files per agent.
3. **Apply.** Pass `auto.tsv` and the agents' output files. A correction is only merged when its target is already a valid root; otherwise the root stays `flagged`, with the suggestion in `status_reason`. Merges go through `merge_roots`, which never violates the `(word_id, form)` unique constraint.
   ```bash
   python3 scripts/review_flagged.py apply es /tmp/review/es/auto.tsv /tmp/review/es/out_*.tsv
   ```

## Agent prompt

> Judge each entry of a Spanish learner's dictionary from your own knowledge. Do not call any API, website or database, and do not edit any file except your output.
>
> Input `<batch>.tsv`: `id<TAB>root<TAB>forms`. Write `<batch>` with `batch_` replaced by `out_`, one line per input line, in the same order:
> - `id<TAB>v`: a real Spanish word, correctly spelled with accents, stored as nouns with their article (`el gato`, `el/la artista`), verbs in the infinitive, adjectives in the masculine singular, other words bare. Regional, colloquial, rare and technical words count.
> - `id<TAB>i`: not Spanish. This covers English and every other foreign word, unless Spanish dictionaries list it as a standard loanword (`el jade`, `el kung-fu`; not `el shell`, `el freemium`). It also covers names, brands, places, acronyms, fragments, run-together words, elongated sounds, and misspellings.
> - `id<TAB>c<TAB>correct root`: a real word stored in the wrong form, and you are certain of the target. Examples: an inflected verb (`componen` → `componer`), a missing or wrong article (`corral` → `el corral`), a diminutive or augmentative (`el gatete` → `el gato`; lexicalized ones like `la maquinilla` are `v`), an unambiguous accent slip (`sillin` → `el sillín`).
>
> If you are not certain of the corrected word, answer `i`. A wrong correction attaches the word to the wrong entry; an `i` only drops it. No reasons, no other output. When done, check that the line count matches the input and reply with one line: the count of v, i and c.

## Measured

On a pilot of 292 roots against hand labels, before the "prefer `i`, be strict on English" rules:
- 90 of 91 real words kept as valid;
- about 1 in 8 corrections of junk pointed at the wrong word;
- 8 junk roots called valid.

The rules in `prepare` settle about 3% of the flagged roots, mostly English copies of Spanish verbs and article mix-ups.

## Status (Spanish, 2026-10-04)

- `prepare` ran once and wrote `auto.tsv` and `batch_000`–`batch_082` (41,313 roots). `auto.tsv` is applied: 668 invalid, 442 merged.
- Applied: batches 002–011. In review when the session ended: 000–001 and 012–021, applied if their `out_*.tsv` exists.
- **To continue:** don't re-run `prepare`; the batch numbering would shift. Re-applying a file gives the same result, so it is harmless. Review the batches without an `out_` file, starting at 022, then `apply`.
- The batch and output files are in `apps/api/data/review/es/` (untracked). If they're gone, run `prepare` again: it only picks up roots that are still `flagged`, so the new batches cover exactly what's left.
