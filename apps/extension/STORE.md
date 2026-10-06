# Chrome Web Store checklist

Build the upload package with `npm run build:store`, then zip the `dist/` folder contents (no source maps).

## Done
- Manifest: name, description (under 132 chars), 16/32/48/128 icons, `homepage_url`, version 1.2.0.
- No remotely hosted code or CDN assets in extension pages (FontAwesome was inlined).
- The `chrome-extension://*/*` web-accessible-resources block stays: it is what makes Parcel build `auth.html` and `reader.html`. Removing it silently drops both pages from `dist/`.
- Minimal privacy page at https://app.langfour.com/privacy (`static/privacy.html` redirects there).
- First-run welcome page, inline login errors, no `alert()` or placeholder buttons.
- Production logging goes through `debugLog` (off unless `REACT_APP_DEBUG=true`).

## Before submitting
1. **Privacy policy.** `apps/web/src/app/privacy/page.tsx` is deliberately two factual sentences and makes no promises. The store may require a fuller policy for an extension that handles account data; write that yourself rather than generating it.
2. **Extension ID.** Uploading assigns the store its own ID. Set `EXTENSION_ID` on the API (CORS, `apps/api/app.py`) to the store ID, and decide whether to keep the `key` field in `manifest.json` (it pins the unpacked dev ID).
3. **Screenshots** (1280x800, at least 1; 3-5 recommended): subtitle highlight with popup, reader with popup, toolbar popup. Small promo tile 440x280.
4. **Store listing text** (below), category *Education*, language English.
5. **Privacy tab answers** (below).

## Listing
Short description: Translate words and add them to your flashcards on YouTube, Netflix and Prime Video, or in a clean reader for any article.

Detailed description: Learn Spanish from what you already watch and read. Langfour highlights the subtitle words you haven't learned yet; hover one to see its translation and add it to your flashcards in one click. Press Cmd/Ctrl+Shift+Y on any article to open a calm reader with the same one-click translations. Words you add show up in your Langfour flashcards.

## Permission justifications
- `storage`: keeps your sign-in session, preferred language and known-word list on your device.
- `activeTab` + `scripting`: reader mode extracts the article from the page you open it on, only after you press the shortcut.
- Host access `app.langfour.com`, `localhost:3000`: lets the Langfour website detect that the extension is installed.
- Host access to the Langfour API and Supabase: sign-in and translation requests.
- Content scripts on YouTube, Netflix and Prime Video: reads on-screen subtitles to highlight unknown words.
- `web_accessible_resources` for `auth_handler`: the magic-link email opens this page to finish signing in.

## Privacy tab
- Collected: email address (authentication), website content (words and passages you translate, subtitle text on supported sites).
- Used only to provide the service; not sold; not used for unrelated purposes or creditworthiness.
- Single purpose: "Translate words while watching video or reading and add them to flashcards."

## Next steps
- Drop `http://localhost:3000/*` from the `siteBridge` matches in the store build.
- Keyboard access to individual words in the reader.
- Automated test of `siteBridge` messaging; lint and typecheck in CI.
- Review whether `host_permissions` for the Koyeb URL should move behind the custom API domain.
