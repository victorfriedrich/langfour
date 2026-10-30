# Grammar curriculum

The chapters and concepts behind the grammar tools of the MCP server
(`docs/plans/grammar-tracking.md`). One folder per language, one file per CEFR level, read in
order: `es/a1.yaml`, `es/a2.yaml`, `es/b1.yaml`, `es/b2.yaml`. The API reads them directly
(`grammar.py`); there are no curriculum tables. A chapter's position is its place in that
sequence. `parse_curriculum` refuses a broken file, and `test_grammar.py` loads the real ones, so
a bad reference fails the tests.

The files are a framework, not a textbook. Each concept says precisely what it covers; the LLM
the user talks to writes the explanation and the examples at teaching time, for that user, with
the words they know. How it should do that is in `teaching_guide.md`, which the server hands to
the client.

Levels follow the Instituto Cervantes *Plan Curricular* (PCIC) as a coverage reference. The PCIC
pages on cvc.cervantes.es returned 404 on 2026-10-29, so the Spanish placement was drafted from
knowledge of the PCIC, not checked line by line against it. The chapter order within a level is
ours: the PCIC lists by grammatical category, not in teaching order.

## Design rules

These are what make the curriculum good. Follow them when editing or extending it (C1, another
language).

1. **One concept, one decision.** A concept is one form pattern or one choice that a single
   sentence can get right or wrong. "Preterite" is a chapter; "hacer in the preterite" and
   "preterite for a completed action at a stated time" are concepts.
2. **Aggregate where one rule generates the forms.** Teach the generator, not the list: the
   present subjunctive comes from the *yo* form, the imperfect subjunctive from the 3rd person
   plural preterite, the conditional reuses the future stems, strong preterites share one set of
   endings. One concept each.
3. **Split where forms must be memorised.** Irregular stems get one concept per verb (hacer,
   poder, querer…), grouped only when verbs really share a pattern (-uv-: tener, estar, andar).
   Split verb classes only where their forms differ (-er and -ir share preterite and imperfect
   endings; they differ in the present only in nosotros/vosotros).
4. **Spiral: the common 80% first, the rest later.** A hard area appears in tiers (Ser o estar
   I, II, III). Tier I covers the cases a learner meets constantly; the exceptions come in a
   later tier, once the learner has the tools for them (ser for where an event takes place needs
   a learner who already uses estar for location without thinking). Tier-I concepts list the
   exceptions they defer under `later`, so a teacher never presents a tier-I rule as absolute.
5. **Forms before choices.** A contrast chapter (perfecto o indefinido, indefinido o imperfecto)
   comes after both sides are known as forms. Form chapters and choice chapters are separate.
6. **Chunks before analysis.** Phrases learners need early (me gustaría, ¿se puede…?, es que…)
   come in as fixed chunks (`chunk: true`); the chapter that explains their grammar comes later
   and points back.
7. **Keep confusable things apart.** Heavy form chapters are interleaved with lighter ones, and
   two things that interfere (por and para, two past tenses) are not introduced back to back
   unless the chapter is the contrast itself.
8. **Each chapter has a goal.** `goal` says what the learner can do afterwards (tell a story
   about a past trip), not what grammar it holds. The teacher uses it to choose practice tasks.
9. **Productive or receptive.** Some concepts at a level only need recognising (`mode:
   receptive`): the -se imperfect subjunctive, voseo, leísmo. They're explained and shown, not
   drilled.
10. **Variety is explicit.** A concept that holds in Spain or Latin America only says so
    (`variety: spain | latam`). Everything else is common to both.
11. **Scope lines are the contract.** A scope states the rule, the forms or cue words that
    trigger it, and its boundary (what it doesn't cover, and where that is). An LLM that reads
    only the scope should be able to teach exactly that concept and nothing from a later one.
12. **Pitfalls are the errors learners actually make**, stated as the wrong form and the right
    one. The teaching LLM adds pitfalls specific to the user's native language.
13. **Forms set the bar for memorised forms.** A concept whose forms must be memorised (rule 3)
    lists them under `forms`, by verb: yo, tú, él, nosotros, ellos, without vosotros, and only
    the ones the concept is about (pidió, pidieron for e → i in the third person). It isn't
    learned until the user has used half of each verb's forms correctly in sentences of their
    own, so list the verbs that matter, not every verb the scope names. Every concept also
    needs two correct sentences (`MIN_CORRECT` in `grammar.py`).

## File format

```yaml
level: a1
chapters:
  - id: es.ser_estar_1            # stable; never renamed once users have data
    title: "Ser o estar I"        # Spanish heading, shown in the overview
    goal: "…"                     # what the learner can do afterwards
    continues: es.estar_hay       # optional: the earlier tier or chapter this builds on
    teach: "…"                    # optional: chapter-wide guidance for the teaching LLM
    concepts:
      - id: characteristic_vs_state   # full id: es.ser_estar_1.characteristic_vs_state
        title: "…"
        scope: "…"
        difficulty: hard          # easy | medium (default) | hard → refresh interval 30/14/7 days
        mode: receptive           # optional; default productive
        variety: spain            # optional; default both
        chunk: true               # optional; taught as a fixed phrase
        lemmas: [hacer]           # optional; verbs a per-verb concept is about (not used yet)
        forms:                    # optional: the forms to cover, by verb (rule 13)
          hacer: [hice, hiciste, hizo, hicimos, hicieron]
        enclitic: true            # optional: the forms take attached pronouns (hazlo, dímelo)
        pitfall: "…"              # optional
        later: [es.ser_estar_2.event_location]   # optional: deferred refinements
        see: [es.estar_hay.location]             # optional: related concepts elsewhere
```

Concept ids are local to their chapter; references in `later` and `see` use full ids. Never
rename an id once users have progress on it: their rows in `user_grammar_concepts` keep the old
id, and the API ignores ids the files no longer have.

## UI copy

`<language>/ui/<level>.yaml` holds what the web app's Grammar tab shows: a short English `title`
and a one-sentence `description` for every chapter and concept, under the same ids and in the
same order as the curriculum. They are labels for a progress screen, not teaching material; the
files above stay the specification. `load_ui_copy` refuses copy that misses or adds an id, so a
new concept needs its copy before the tests pass.

```yaml
level: a1
chapters:
- id: es.ser_estar_1
  title: 'Ser or estar: essentials'
  description: Describe what someone is like versus how they are now.
  concepts:
  - id: characteristic_vs_state
    title: Characteristics versus states
    description: Ser for typical qualities; estar for current conditions.
```

A concept may also name an `image` in its curriculum entry: a file in
`apps/web/public/grammar/<language>/`, shown beside it on the lesson page.
