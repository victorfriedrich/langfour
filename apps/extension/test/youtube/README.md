# YouTube fixtures

Rendered YouTube cards that `src/youtubeSelectors.ts` is checked against
(`src/youtubeSelectors.test.ts`). YouTube builds its pages in the browser, so
these are DOM snapshots, not the HTML the server sends, trimmed to the cards
and scrubbed: titles and long texts read "Texto", avatars, menus and metadata
rows are gone. What the selectors use is kept as captured: the card elements,
the thumbnail link, the thumbnail box and the duration label.

| File | Page | Cards |
|---|---|---|
| `home.html` | Home (channel Videos tabs use the same cards) | video lockup, Short in the Shorts shelf, older grid card linking a Short |
| `search.html` | Search | video, live stream, Short |
| `watch-sidebar.html` | Watch page sidebar | two video lockups |

## Recapturing

When badges stop appearing, open the page on www.youtube.com, paste this into
the DevTools console, and replace the cards in the matching file with what it
copies (it copies the first three cards on the page):

```js
copy([...document.querySelectorAll('ytd-rich-item-renderer, ytd-video-renderer, yt-lockup-view-model')]
  .filter((c) => !c.parentElement.closest('ytd-rich-item-renderer, ytd-video-renderer, yt-lockup-view-model'))
  .slice(0, 3)
  .map((card) => {
    const c = card.cloneNode(true);
    c.querySelectorAll('svg, script, style, ytd-menu-renderer, yt-touch-feedback-shape, yt-decorated-avatar-view-model, yt-content-metadata-view-model, button-view-model').forEach((x) => x.remove());
    for (const x of [c, ...c.querySelectorAll('*')]) x.removeAttribute('style');
    return c.outerHTML;
  })
  .join('\n'));
```

Then run `npm test -- youtubeSelectors` in `apps/extension` and fix the
selectors until it passes.
