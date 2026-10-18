# Reader corpus

Real pages the reader's article extraction (`src/articleExtraction.ts`) is
checked against. The pipeline uses general signals, never per-site
selectors, so a change is judged by what it does across many sites:

1. **Prune** what the page declares is not content: scripts and widgets,
   hidden elements (but not `hidden="until-found"`, which is collapsed
   content), dialogs, navigation, banners, sidebars. In the browser, layout
   also removes what is not displayed, fixed overlays and screen-reader-only
   text.
2. **Extract** with Mozilla Readability.
3. **Normalize**: reading elements only; drop link-dense blocks, stray labels,
   date and time lines, reference markers and endnote lists, icons; trim
   non-sentences and publisher promotions from the edges; add recipe
   ingredients from schema.org data when Readability dropped them.

## Running it

```bash
cd apps/extension
node scripts/fetch-reader-corpus.mjs   # once; --refresh to fetch again
npm run test:corpus
```

The fetch script saves each page as headless Chrome renders it on a phone
(the reader works on the rendered page, cookie walls included) into
`apps/extension/.corpus-cache/`, which is gitignored: only the URLs are
committed. The test fails when a page yields no article, too little of one,
or an article where `urls.txt` says there is none. It also writes:

- `.corpus-cache/report.md`: words, paragraphs, headings and images per page,
  plus short blocks and boilerplate-like lines, which is where extraction
  mistakes show up;
- `.corpus-cache/out/<name>.html`: each extracted article, to read.

The tests run in jsdom: happy-dom's parser stops partway through large
pages. Headless Chrome has no layout-based pruning in this setup (the page
is re-parsed without styles), so print-only notices and screen-reader-only
labels show up here that the browser removes.

## Adding pages

Add a line to `urls.txt` (`<name> <language> <url>`, plus `none` for a page
that is not an article), fetch, run. Pages worth adding are ones from a
kind of site the corpus does not cover yet.
