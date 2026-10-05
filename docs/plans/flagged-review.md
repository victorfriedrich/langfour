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

`merge_roots` moves the source's `userwords`, `srs_notes` and `flashcardtests` rows to the target. A user who already has the target keeps that row; it becomes known if the source was, takes the source's review progress if further along, and gets the source's tests and RemNote note. The source row is then deleted, unless the user has a note on both (two Rems for one word). The source's bare root becomes a form of the target only when the source has no forms. Only apply a correction whose root is still `flagged`: re-merging an already merged root would add its bare root to the target again.

## Lessons from the Spanish run

- Jev flagged the right roots; the damage came after, in steps that ignored forms. The article rule merged "debate" (holding debatir's conjugation) into el debate; it now requires the source's forms to be just the word and its plural. Renaming a flagged root keeps its forms, which can be invented conjugations (chalaa, chalaaba): check forms after any rename.
- Strict agents drop ~3-5% of rare real words. A rescue pass that lists only the mistakes, on the `i` verdicts, brought back 468 of 13,291 (batches 034-082) and far fewer in 000-033, where the review was less strict. Read rescues before applying: agents also "rescue" names and English.
- Jev's root score separates real words from junk only weakly (rescued median 0.37, junk 0.19) and its form scores barely at all (invented conjugations score ~0.85; the flag line is 0.3). The root-alone veto also let through roots that copy a real verb's forms (romp, usare, seguire); find those by form overlap with another valid root.
- "-ares" forms are not junk: on -ar verbs they are the archaic future subjunctive, on nouns in -ar/-er/-ir they are plurals.

## Status (Spanish, 2026-10-05, done)

- No roots are `flagged`: 35,185 valid, 38,062 invalid.
- 2026-10-04: 345 English or label forms removed, bien / la radio / molar restored, 538 user rows moved. 2026-10-05: the last 1,518 flagged roots decided by hand (837 renamed to their correct root, 632 merged, 40 invalid, 11 wrongly invalid targets such as os and nato revived); verb conjugations removed from 15 nouns (el debate, el censor, el vasar…); 2,875 duplicate user rows merged into their target; 468 rare words rescued; 2026-10-05 second pass: batches 000-033 rescued, the 2,645 highest Jev-scored invalid roots read by hand (107 more fixed), 31 valid copy roots merged into the verb they copy, and stray forms that are another word's root removed (lama on llamar, regla on siglar).
- A CSV backup from before the 2026-10-04 cleanup is in `apps/api/data/backup-2026-10-04/`. The batch, output and rescue files are in `apps/api/data/review/es/` (untracked).
