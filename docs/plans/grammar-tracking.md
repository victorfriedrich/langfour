# Grammar tracking

Status as of 2026-10-29: built in PR #71, not merged; `sql/grammar.sql` applied to the live database the same day. Covers how Langfour keeps track of the grammar
a user has worked through, so the LLM a user talks to through the MCP server can write texts with
grammar they know, teach the next chapter, and work fading rules back into what it writes.
Written after the vocabulary tools (`get_vocabulary`, `record_practice`, `score_text`,
`record_exposure`, `set_word_status`) shipped in `apps/api/mcp_server.py`.

## 0. Principles

- **The server serves cheap, structured data; the client does the thinking.** The user's Claude
  or ChatGPT decides which rules a text uses, whether a sentence got a rule right, and what to
  teach next. The server stores its verdicts and returns state. No LLM, spaCy or other analysis
  runs on the server for these tools.
- **The user learns like reading a book.** Chapters come in a fixed order and the user works
  through them. That is the main progress model.
- **Refresh is a helper, not a review queue.** Hard grammar gets forgotten, so each rule the user
  has used carries a refresh date. When it passes, the client works the rule back into texts and
  examples without making a drill of it. The user never sees a "due" list.
- **Grammar is fine-grained.** A concept is something one sentence can use right or wrong, not a
  textbook heading.

## 1. Curriculum

Two levels: **chapters** (what the user works through, ~60–80 for all of Spanish) and
**concepts** (the rules inside a chapter, ~800–1,000 for all of Spanish). Chapters are ordered;
the order is the book, so there is no separate prerequisite graph.

**Source: the Instituto Cervantes *Plan Curricular* (PCIC)**, decided 2026-10-29. Its grammar
inventory says what belongs at each level, A1 to C2, but it is organised by grammatical category
(noun, verb, pronoun, …), not as a teaching sequence. So the levels give the coarse order and the
chapter order within a level is ours: the LLM drafts it, the author reviews it. The PCIC is used
as a reference for what to cover; titles, explanations and examples are written fresh, not copied.

The curriculum lives in versioned files, one per level (`apps/api/grammar/es/a1.yaml` …
`b2.yaml`), and is upserted into the database by a script. Spanish A1–B2 was drafted on
2026-10-29 and reviewed the same day: 89 chapters, 458 concepts. The file format and the full design rules (spiral tiers,
aggregation, chunks, receptive concepts, varieties) are in `apps/api/grammar/README.md`. IDs are
stable slugs (`es.indefinido_irregular.hacer`). A concept that is removed from the file is marked
retired, never deleted, so user data keeps pointing at something.

**The files are a framework, not a textbook.** A concept stores a precise `scope` (the rule, its
cue words, its boundary), not explanations or examples. The user's LLM writes those at teaching
time, for that user and with words they know. `apps/api/grammar/teaching_guide.md` tells it how,
including the vocabulary rule for examples: only known or learning words while a concept is new,
and at most one new word per sentence once it is fresh.

### Granularity rules

- **Split by verb class only where the forms differ.** Preterite and imperfect endings are the
  same for -er and -ir verbs (comí/viví, comía/vivía), so those are one concept each. The present
  differs only in nosotros/vosotros (comemos/vivimos), so -er and -ir are separate there.
- **One concept per irregular verb**, roughly the 40 most frequent. Groups only where there is a
  real pattern. For the preterite:
  - own concepts: hacer (hice/hizo), dar, ver, querer, venir, poder, poner, saber, caber, …
  - groups: -uv- (tuve, estuve, anduve); -j- with -eron (dije, traje, conduje); e→i in the third
    person (pidió, sirvió, sintió); o→u (durmió, murió); y spelling (leyó, cayó, oyó)
  - ser and ir share fui: one concept
- **Compound verbs belong to their base verb**: deshacer and rehacer go under hacer; mantener,
  obtener and contener under tener. They are listed in the concept's scope, not given concepts
  of their own.
- **Usage chapters split into individual uses.** Por vs para is one concept per use (cause,
  purpose, deadline, exchange, …), not one concept for the contrast.
- A per-verb concept lists its verbs (`lemmas`), so grammar and vocabulary can refer to each
  other later. Nothing reads them yet.

### Per concept

| Field | Example |
|---|---|
| `id` | `es.indefinido_irregular.hacer` |
| `title` | hacer: hice, hizo |
| `scope` | hice, hiciste, hizo (z), hicimos, hicisteis, hicieron. Compounds: deshice, rehízo. |
| `difficulty` | easy / medium / hard → `base_interval_days` 30 / 14 / 7 |
| `mode` | productive, or receptive (seen counts as practice; not drilled) |
| `variety` | both, spain or latam |
| `chunk` | taught as a fixed phrase, analysed in a later chapter |
| `pitfall` | the error learners make (*tuvé → tuve*) |
| `later` / `see` | the deferred refinements of a tier-I rule / related concepts |
| `lemmas` | the verbs, for per-verb concepts |

## 2. Data model

```
CURRICULUM   apps/api/grammar/<language>/<level>.yaml, read by grammar.py; not in the database

PROGRESS     user_grammar_chapters(user_id, chapter_id, status, started_at, finished_at)
             status: started | done            -- no row = not started

REFRESH      user_grammar_concepts(user_id, concept_id, first_correct_at, last_seen_at,
                                   last_produced_at, interval_days, interval_grown_at,
                                   refresh_at, produced_count, error_count)

EVIDENCE     grammar_events(id, user_id, concept_id, kind, correct, self_reported,
                            sentence, source, occurred_at)      -- append-only
             kind: seen | produced
```

- **The curriculum stays in the files.** First planned as two seeded tables; built without them,
  because a seed step is one more thing to fall out of date and nothing in the database needs to
  join on the curriculum. The API loads the files once per process. `chapter_id` and
  `concept_id` are the slugs from the files, with no foreign key.
- `grammar_events` is the record of what happened, like `word_events`: never updated or deleted
  from. `user_grammar_concepts` is the current refresh state. Python computes the new rows and
  one SQL function (`record_grammar`) writes events, concepts and chapters in one transaction.
- Several chapters can be started at once (a user may skip ahead or go back).
- RLS: users select their own rows. Writes go only through `record_grammar`, executable by the
  service role alone, the way `srs_card_sm2` revokes direct writes.
- Nothing here touches `srs_notes`, `srs_cards` or `srs_reviews`, and nothing goes to RemNote.

### Concept state (derived, shown to the client)

| State | Meaning |
|---|---|
| not yet | its chapter hasn't been started |
| studied | its chapter is started or done, but the user hasn't produced it correctly |
| fresh | produced correctly, `refresh_at` in the future |
| fading | `refresh_at` has passed |

## 3. Refresh rule

`practise()` in `grammar.py`, a pure function with unit tests. The SQL only stores its result.

- **First correct production**: `interval_days = base_interval_days`,
  `refresh_at = now + interval`.
- **Later correct production**: the interval doubles (cap 180 days) only if at least half of it
  has passed since it last grew; otherwise only `last_produced_at` moves. Using a rule five times
  in one chat therefore counts once.
- **Error**: the interval halves (floor 1 day) and `refresh_at = now + 1 day`, so the rule shows
  up as fading again soon.
- **Seen** (the client used the rule in a text the user read): if the rule is fading,
  `refresh_at = now + interval / 2`; the interval doesn't grow. Seen on a fresh rule changes
  nothing but `last_seen_at`.
- **Self-reported** ("I know por vs para well"): counts as a first correct production, which
  takes the user at their word, as `set_word_status` does for words.
- **Receptive concepts** (`mode: receptive`) are never drilled, so `seen` counts for them the
  way a correct production does for the others.

## 4. MCP tools

Three tools: two reads at different levels of detail, one write. Rejected instead: extending
`get_vocabulary` and `record_practice` to take concept IDs.

### `get_grammar_overview(language?)`

One line per chapter, returned as a single preformatted text field rather than a JSON list. At
~15 tokens a line that is about 1k tokens for the whole curriculum. JSON would be about 3× that.

```
Spanish grammar · started: es.subj_presente

✓ es.pret_regular      Pretérito: regulares        all fresh
✓ es.pret_irregular    Pretérito: irregulares      19 of 22 fresh, 1 fading
✓ es.por_para          Por vs para                 3 of 6 produced
→ es.subj_presente     Subjuntivo presente         2 of 9 produced
· es.subj_vs_ind       Subjuntivo vs indicativo
…
```

Description: call once at the start of a session where you'll write or teach Spanish, to know
broadly what grammar you can use.

Every call also returns `teaching_guide.md` (~5.6k characters, ~1.4k tokens): how to explain
from a scope, choose example vocabulary, practise, correct and record. The server is stateless,
so it can't tell the first call of a session from a later one; the guide's cost is the price of
that. For the 89 Spanish chapters the overview itself is ~4k characters (~1k tokens).

### `get_grammar_details(language?, chapters?, concepts?)`

- **Chapter IDs** (up to 3): the chapter's goal and teaching note, and every concept with its
  state, title and scope. For "which subjunctive forms can I use in this text?"
- **Concept IDs** (up to 10): also pitfall, `later` and `see` (with the titles of the concepts
  they point to), mode, variety and chunk. For teaching or correcting a specific rule.
- Unknown IDs come back in a `not_found` list instead of failing the call.

Description: only for the chapters the conversation is actually about. A text about por vs para
needs `es.por_para`, not the subjunctive.

### `record_grammar(language, results, chapters?)`

```
results:  [{concept, kind: seen | produced, correct?, self_reported?, sentence?}]
chapters: [{chapter, status: started | done}]
```

- Called once, at the end of the session, with one result per concept and kind.
- `correct` is required for `produced`. Plain booleans, as in `record_practice`, so ChatGPT and
  Claude record verdicts the same way.
- `sentence` (up to 300 characters) is the user's sentence, kept so the client's grading can be
  checked later.
- `chapters` is for when the user says they started or finished one; take them at their word.
- Returns which concepts changed state (studied → fresh, fading → fresh, …) and any unknown IDs.

### Server instructions

Add to `FastMCP(instructions=...)`: before writing a text or teaching grammar, read
`get_grammar_overview`; fetch details only for the chapters involved; prefer grammar the user
has studied, and work in fading rules where they fit naturally; teach from the started chapter
when asked; at the end, report what the user produced (and what you used in texts they read)
with `record_grammar`.

## 5. Steps

1. **Curriculum for Spanish A1–B2.** Drafted 2026-10-29 (`apps/api/grammar/es/`), plus the
   README and the teaching guide. Left: the author's review, and a check against the PCIC
   inventory once its pages can be reached (they returned 404). The draft passes a structural
   check: YAML parses, IDs unique, fields valid, every `later`/`see`/`continues` reference
   resolves and `later` never points backwards. That check is `parse_curriculum` in `grammar.py`.
2. **SQL** in `apps/api/sql/grammar.sql`: three tables, RLS, `record_grammar`. Applied
   2026-10-29 as migration `grammar`, checked live: RLS on, select-own policies only, no
   client writes, `record_grammar` executable by the service role alone, and a rolled-back
   call wrote the expected rows.
3. **Python** in `apps/api/grammar.py`, following `vocabulary.py`: curriculum loading and
   validation, the store, the overview formatter, the refresh rule. `test_grammar.py` covers
   them; `test_mcp_server.py` calls the tools over HTTP. The three tools and the instructions are
   registered in `mcp_server.py`. PyYAML is a new runtime dependency. Built.
4. **Try it in ChatGPT and Claude** on the author's account: overview size in tokens, whether the
   clients fetch details sparingly, whether `record_grammar` gets called at the end without
   prompting.

Later, not in this plan: a web page for the book (chapter list, mark started/done), other
languages, and `score_text` flagging irregular forms whose grammar concept the user hasn't
studied.

## 6. Open questions

- **Done chapters with unproduced concepts**: they show as `studied` indefinitely. Fine for v1;
  maybe they should fade too.
- **Curriculum edits**: splitting a concept after users have data on it. Proposed: the old ID is
  dropped from the file (its rows are then ignored) and its state copied to the new IDs by hand
  in SQL.

## 7. Rejected alternatives

| Idea | Why not |
|---|---|
| Track grammar per wordform | `wordforms` is `(id, word_id, form)` with no tense or person, one row per string (hablamos is present and preterite), and conjugation knowledge carries over between verbs. |
| Levels from counts (seen N times, produced M times) | A home-made spacing rule. The refresh interval does the same job and handles forgetting. |
| Grammar as SRS cards in `srs_notes` | The user learns by chapter, not from a due queue. It would also need `srs_notes.word_id` made nullable, touching every query that reads notes. |
| spaCy morphology on the server for exposure | The client already knows what it put in a text. |
| Server-side judgment (Jev) of correctness | The MCP serves data; the client judges. |
| One flat overview listing every concept | ~10k+ tokens at full granularity; most conversations touch one or two chapters. |
