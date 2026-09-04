# Langfour

Langfour turns the content you already watch and read into personalized vocabulary practice.

Its Chrome extension translates unfamiliar words in place on YouTube, Netflix, Prime Video and any article page, saving them to a vocabulary collection. The web app turns that collection into spaced-repetition practice, and ranks 11,800 YouTube videos by how much of each one you can already understand.

<!-- TODO: add a 30–60 s demo video link once recorded. -->

![The Videos page: YouTube videos ranked by how much of their vocabulary you already know, each card showing the share of known words and the number of new ones](docs/images/recommendations.png)

[![Extension CI](https://github.com/victorfriedrich/langfour/actions/workflows/extension-ci.yml/badge.svg)](https://github.com/victorfriedrich/langfour/actions/workflows/extension-ci.yml)

## Why Langfour?

Learners are stuck choosing between authentic content that is too hard and graded material that is not interesting. Research on extensive reading puts the sweet spot around 95% known words — but nothing tells you which video that is.

Langfour:

- Tracks your vocabulary as dictionary root forms rather than raw strings
- Highlights and translates unfamiliar words while you browse
- Scores 11,800 YouTube transcripts against that vocabulary
- Turns saved words into flashcards, example sentences and matching exercises

## Features

### Reader Mode

`Command + Shift + Y` (`Ctrl + Shift + Y` on Windows and Linux, rebindable at `chrome://extensions/shortcuts`) converts the current article into a focused reading view.

- Extracts the article body with Mozilla Readability, dropping navigation, ads and comments
- Highlights every word not yet in your vocabulary
- Click a word to translate it and add it in one step
- Select a passage for a context-aware translation, not word by word

![Reader Mode highlighting unfamiliar words in a Spanish news article](docs/images/reader-mode.webp)

> **Limitations:** any page Readability can parse — most news sites and blogs, but not paywalled or heavily scripted ones. Spanish, German, Italian and French.

### YouTube Subtitle Integration

Langfour enhances the platform's own captions rather than replacing them.

- Unfamiliar words are highlighted in orange
- Hovering pauses playback and shows a translation; moving away resumes it
- Words save to your collection without leaving the video
- Works on Netflix and Prime Video too

![YouTube subtitles with unfamiliar words highlighted and a translation popup on hover](docs/images/youtube-subtitles.webp)

> **Limitations:** the video needs real subtitles in your target language; auto-translated captions are not supported.

### Personalized Video Recommendations

The **Videos** page ranks categorized YouTube videos by how much of their vocabulary you already know. Each card shows the share of words you already understand and how many new words the video would teach.

You can filter by category and preview a video inline. Videos you have already watched are excluded, as is anything under 100 unique words.

### Vocabulary-Based Content Discovery

**Words Known → Add Common Words** runs the same index backwards: instead of scoring videos by the words you know, it scores words by how many videos contain them.

Pick a category and Langfour lists the words you do not know yet, most widely used first, each with the percentage of that category's videos it appears in. Mark the ones you already recognise as known, or shift-click a range to add the rest at once.

![Words Known → Add Common Words: unfamiliar words ranked by how many Travel videos they appear in](docs/images/vocabulary-frequency.png)

### Practice

#### Flashcards

A spaced-repetition session over the words due today; each answer updates the word's next review date. A writing mode asks you to type the word instead of flipping the card.

- `Space` — flip
- `Right Arrow` — correct, or next card
- `Left Arrow` — incorrect

#### Words in Context

For five words at a time, the backend generates short A1–A2 sentences with the targets highlighted, followed by a word-to-translation matching game over the same five. Results feed the same schedule as the flashcards.

### Progress

**Words Known** charts your vocabulary size over time, lets you search, edit and remove saved words, and shows which content categories your vocabulary already covers.

### Imported Media

The **Media** page imports your own episode transcripts as timestamped JSON. They are parsed into the same vocabulary model and become recommendable, so you can learn an episode's words before watching it.

## Importing from Anki

Export your deck as an **`.apkg` package** or as **Notes in Plain Text** (`.csv`, tab-separated, no header) and upload it from **Words Known → Import**; pasting tab-separated lines works too. Front should hold the word, Back the translation, and other fields are ignored.

- `.apkg` files are read straight from the bundled SQLite collection, including recent Anki's compressed `collection.anki21b`
- HTML, `[sound:...]` tags and media references are stripped; RemNote's nested folder lists are reduced to the leaf item
- Words are matched against the dictionary including inflections, so `hablaba` imports as `hablar`; unmatched words are resolved by a language-model lookup you review first
- You choose whether imports land as *learning* (they enter the practice schedule) or *known* (they only affect recommendations)
- Spanish and Italian decks only

![Anki import screen](docs/images/anki-import.png)

## Running Langfour Locally

Requires Node.js 20+, Python 3.11+ with `venv`, a [Supabase](https://supabase.com) project and an [OpenRouter](https://openrouter.ai) key. `ffmpeg` is only needed to transcribe videos that have no subtitles.

```bash
git clone git@github.com:victorfriedrich/langfour.git
cd langfour
npm install
npm run api:install
```

Each app gets its own environment file, because the three ship with different trust levels:

```bash
cp apps/web/.env.sample       apps/web/.env
cp apps/extension/.env.sample apps/extension/.env
cp apps/api/.env.sample       apps/api/.env
```

Fill in the Supabase and OpenRouter values — each sample documents where to find them — then:

```bash
npm run dev          # web on :3000, API on :8000
npm run api:test     # API tests
```

> **On the name.** The product is Langfour everywhere it is user-visible, but internal identifiers keep an earlier `langfive` prefix: the `LANGFIVE_*` variables, the `langfive-corpus` bucket, the `langfive-corpus-api-readonly` role and the `langfive-api` image tag. Renaming them means changing the deployed environment, bucket and IAM role in lockstep, so they are left alone deliberately.

> **Setup gaps.** The database schema lives in the hosted Supabase project rather than as migrations here, so a from-scratch setup needs it applied by hand. Without `LANGFIVE_CORPUS_*` configured, the recommender starts with whatever is in `apps/api/data/processed/`.

### Chrome extension

```bash
npm run build:ext    # writes apps/extension/dist
```

Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked** and select `apps/extension/dist`. Or download the prebuilt extension from the [live app](https://app.langfour.com/extension).

## Project Status

A working prototype I use daily — deployed and usable, not a polished product.

- **Browsers:** Chrome only (Manifest V3), distributed as a zip rather than through the Web Store.
- **Languages:** Spanish, German, Italian and French are supported in code, but the hosted app enables Spanish only, and the corpus is 10,650 Spanish videos out of 11,800. Anki import covers Spanish and Italian.
- **Recommendations:** ranked on unique-word coverage alone — not word frequency within a video, grammar or speaking speed.
- **Setup:** the database schema is not versioned here.

Planned: export the schema as migrations; weight the recommender by in-video frequency and target ~5% new words rather than raw coverage; enable the other three languages once their corpora justify it; ship on the Chrome Web Store; add Firefox support; end-to-end extension tests against recorded pages.

## What I Learned

**Silent failures are worse than crashes.** The most expensive bug here was a backend deployed with the wrong database key after row-level security went on. Nothing errored — every query returned an empty list with HTTP 200, and the app quietly treated all words as unknown. The fix was not a better test but a boot-time check that inspects the key's own role claim and refuses to start, plus a rule that an empty dictionary cache is never legitimate.

**Memory is a first-class constraint on small hosts.** The first recommender held both the list-of-lists corpus and the sparse matrix; the first corpus loader read a 118 MB archive into RAM before extracting it. `tracemalloc`, CSR-only storage and streaming tar extraction brought the API well under a small container's limits, and taught me to measure peak RSS rather than assume it.

**One source of truth for identifiers.** Languages were ISO codes in some places and English names in others, across six independent mapping tables — two of which were missing French, so French learners were silently served Spanish vocabulary. Collapsing them into one `languages` module per app, converting only at the boundary and returning `None` rather than a default on unknown input, removed the whole class of bug.
