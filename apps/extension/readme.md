# LangfourExtension

## Features

### Add words to flashcards from YouTube and Netflix
Hover over YouTube subtitles to translate words and add them to flashcards. Words you haven't added to flashcards are orange.

### Reader mode for newssites
Configure a shortcut in the extension settings or use the default CMD-Shift-Y to activate a reader mode and translate individual words / sections. 

## Credits
Subtitle-related features for Netflix and YouTube are based off [Spotlight-Lingo by Eugene Gluhotorenko](https://github.com/gevgeny/Spotlight-Lingo/).

## Favourite channels on YouTube

Channel pages get a Favourite button next to Subscribe and a Langfour tab
(`src/youtubeChannel.ts`). The tab says how many of the channel's videos are
indexed, how much of them you understand and how many are at your level, lists
the words the channel uses most that you don't know, and links its three
videos you'd understand most of. The API side is
`apps/api/channel_routes.py`:

- `GET /api/channels/{channel_id}?language=es`: the tab's progress, core words and easiest videos
- `GET /api/channels/{channel_id}/favourite`: the button's state
- `POST /api/channels/{channel_id}/favourite` with `{"language", "favourite"}`
- `POST /api/channels/{channel_id}/core-words` with `{"language"}`
