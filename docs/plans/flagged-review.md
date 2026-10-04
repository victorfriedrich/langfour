# Reviewing flagged dictionary roots

Roots the Jev audit could not settle (`words.status = 'flagged'`) get a definite verdict from rules, then from Claude agents running on the Claude plan (not OpenRouter).

## Run it

1. **Prepare.** Writes `auto.tsv` (rule decisions) and `batch_NNN.tsv` (500 roots each, `id<TAB>root<TAB>up to 6 forms`):
   ```bash
   cd apps/api && python3 scripts/review_flagged.py prepare es --out /tmp/review/es
   ```
2. **Review.** For each batch file, one Sonnet subagent (`Agent`, `model: sonnet`) with the prompt below. Run about 6 at a time, 2 batch files per agent.
3. **Apply.** Pass `auto.tsv` and the agents' output files. A correction is only merged when its target is already a valid root, and only when the source's bare root is one of its own forms or it has none; otherwise the root stays `flagged`, with the suggestion in `status_reason`. The second rule stops a mislabelled root (`el milk`, forms `leche`) from adding `milk` to `la leche`. Merges go through `merge_roots`, which never violates the `(word_id, form)` unique constraint.
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
> If you are not certain of the corrected word, answer `i`. A wrong correction attaches the word to the wrong entry; an `i` only drops it. Some batches contain runs of garbled transcript where a letter is missing throughout (`dspués`, `otograía`, `verdd`); answer `i` for those, do not reconstruct them. No reasons, no other output. When done, check that the line count matches the input and reply with one line: the count of v, i and c.

## Measured

On a pilot of 292 roots against hand labels, before the "prefer `i`, be strict on English" rules:
- 90 of 91 real words kept as valid;
- about 1 in 8 corrections of junk pointed at the wrong word;
- 8 junk roots called valid.

The rules in `prepare` settle about 3% of the flagged roots, mostly English copies of Spanish verbs and article mix-ups.

## Checking agent output

Before applying, check each `out_` file: same ids in the same order as its batch, every line `v`, `i` or `c<TAB>root`, and a look at the `i` verdicts on roots with 5+ forms (real words hide there). Problems seen in the Spanish run:
- One agent marked ~40 common words `i` (la cama, el perro); re-run the batch.
- One wrote line numbers instead of ids; the verdicts were in order and were mapped back by position.
- Agents decoded garbled transcript (`dspués` → `después`) into corrections. Turn those stretches into `i` before applying.
- Later agents wrote verdicts with a script that defaults unlisted ids to `i` (or once `v`); read the `v` list when the default is `v`.
- About 3-5% of `i` verdicts in batches 034-082 are rare real words (la anticorrosión, la tosta). They are findable by `status_reason = 'review: invalid'`.

## User data

`merge_roots` moves the source's `userwords`, `srs_notes` and `flashcardtests` rows to the target, unless the user already has the target (then they stay on the source), and adds the source's bare root as a form only when the source has no forms. Only apply a correction whose root is still `flagged`: re-merging an already merged root would add its bare root to the target again.

## Status (Spanish, 2026-10-04, done)

- All 83 batches are reviewed and applied. 1,518 roots stay `flagged`, each with an agent's suggested root in `status_reason` whose target is not a valid root.
- On 2026-10-04 a cleanup fixed earlier merges: 345 English or label words removed from Spanish roots (more → más, red → rojo), bien, la radio and the verb molar restored, and 538 user rows moved from merged roots to their targets. A CSV backup taken before it is in `apps/api/data/backup-2026-10-04/`.
- The batch and output files are in `apps/api/data/review/es/` (untracked).
