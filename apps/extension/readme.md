# LangfiveExtension

## Features

### Add words to flashcards from YouTube and Netflix
Hover over YouTube subtitles to translate words and add them to flashcards. Words you haven't added to flashcards are orange.

### Reader mode for newssites
Configure a shortcut in the extension settings or use the default CMD-Shift-Y to activate a reader mode and translate individual words / sections. 

## Credits
Subtitle-related features for Netflix and YouTube are based off [Spotlight-Lingo by Eugene Gluhotorenko](https://github.com/gevgeny/Spotlight-Lingo/).

## Backend bookmark endpoints

The bookmark button on YouTube communicates with the backend using two simple endpoints:

### `POST /youtube/bookmarks`

Queue indexing for a channel.

Request body:

```json
{ "channel_id": "<channel identifier>" }
```

Response example:

```json
{ "status": "queued" }
```

### `GET /youtube/bookmarks/{channel_id}`

Check if a channel was already indexed. The response returns a boolean flag.

```json
{ "saved": true }
```
