# Langfour for RemNote

Practice your Langfour words in RemNote. Every word you save in Langfour
becomes a RemNote flashcard. RemNote schedules the reviews, and the results
go back to Langfour so it knows how well each word is learned.

## What it does

- **Creates cards.** Each learning word in Langfour becomes a Rem under
  `Langfour / <Language> / <Month>`, filed by the month you saved it: the
  word on the front, its translation on the back. Both directions by
  default; this can be changed in the settings. Words you have marked as
  known in Langfour are skipped.
- **Uses flashcards you already have.** Before creating a card, the plugin
  looks for a flashcard anywhere in RemNote whose front or back is the word
  (ignoring case, articles and list separators such as commas or slashes).
  If it finds one, it links that card instead, so its reviews count in
  Langfour. Turn this off in the settings. **Langfour: Link existing
  flashcards** does the same for cards the plugin already created: it links
  your own card and deletes the copy, but only copies inside the Langfour
  document that were never reviewed.
- **Reports reviews.** Every graded review RemNote records (Again, Hard,
  Good, Easy) and each card's next due date are sent to Langfour, a few
  seconds after you answer the card.
- **Shows progress.** **Langfour: Open progress** shows how many words you
  have learned (every card at an interval of 3+ weeks), how that number grew
  over 90 days, which words you learned this week, and which keep slipping.
  Click a word to open its Rem.
- **Respects deletions.** If you delete a card's Rem, Langfour records that and
  does not create the card again.
- **Stops words you turn off.** Turning a word's flashcards off in RemNote, or
  deleting its Rem, stops the word in Langfour too; turning them back on, or
  restoring the Rem, resumes it. Its review history is kept either way.

Syncing is automatic: when RemNote starts (desktop or mobile), every hour
while it is open, and when you open the progress page. Answers and turned-off
cards are sent as they happen in between. **Langfour: Sync now** exists in the command
palette for troubleshooting. Disconnecting in Langfour revokes the token; the
plugin notices on its next sync and asks to connect again.

## Setup

1. Install this plugin (see *Development* below while it is unlisted).
2. Run **Langfour: Connect** and click **Connect**. The plugin shows a code
   and a link to Langfour; approve the code there. Nothing needs copying:
   the plugin collects its token itself, and the token can only sync words
   and reviews.

**Permissions.** To find flashcards you already have, the plugin reads your
whole knowledge base and may tag a matching card with its powerup. It only
creates Rems inside its **Langfour** document, and only deletes there: the
duplicates described above.

Connecting RemNote moves your reviews there: Langfour's own practice
session is hidden so a word is not scheduled twice. Disconnecting in
Langfour moves them back. Your RemNote cards stay either way.

## Development

```bash
npm install
npm run dev        # serves the plugin on http://localhost:8080
```

In RemNote: Settings → Plugins → Build → **Develop from localhost**, and
enter `http://localhost:8080`. The plugin runs only while the dev server
is running. To use the API on your machine, set **Langfour API URL** in the
plugin settings to `http://localhost:8000`, and start the API with
`WEB_APP_URL=http://localhost:3000` so the approval link opens the local web
app.

```bash
npm test           # progress calculations
npm run check-types
npm run build      # dist/ and PluginZip.zip
```

`npm run validate` runs RemNote's manifest check. It expects the plugin to
be the root of its own git repository, so it only works in a standalone copy.
Uploading the plugin as unlisted also needs `repoUrl` in
`public/manifest.json` to point to a public repository.

## How it works

| File | Role |
|---|---|
| `src/widgets/index.tsx` | Registers settings, the `langfour_word` powerup, the commands and the progress page, then syncs on start and on a timer |
| `src/sync.ts` | One sync: link or create Rems for pending words, push cards and reviews, then send the list of Rems that still exist |
| `src/match.ts` | Matching a word to a flashcard the user already has |
| `src/stats.ts` | The progress calculations |
| `src/widgets/progress.tsx` | The progress page |
| `src/api.ts` | Client for the API's `/pair/remnote` and `/sync/remnote` endpoints |
| `src/connection.ts` | The stored token and waiting for a pairing to be approved |

The server side is `apps/api/remnote_sync.py` and `apps/api/sql/remnote_sync.sql`.
Each Rem stores its Langfour word id in a hidden powerup slot, and nothing
else: the language and save date come from the API. That id is how a sync
that stopped half-way recovers without creating duplicates.
