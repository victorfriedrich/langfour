# Langfour Reader for Safari on iOS

The reader mode of `apps/extension`, packaged as a Safari web extension inside
a small iOS app, plus tappable YouTube captions on m.youtube.com: YouTube's own
captions (including auto-generated ones) get word marks, and a tap on a word
opens its translation and pauses the video. Netflix and Prime Video are left
out. The subtitle script runs as a content script, because Safari applies
YouTube's CSP to injected <script> tags. iPhone fullscreen would hand the
video to iOS's own player, where no page captions can show, so the extension
leaves that player at once and stretches YouTube's page player over the screen
instead (src/iosFullscreen.ts); turned sideways, one swipe up hides Safari's
bars.

Generated with `xcrun safari-web-extension-converter --ios-only`, then changed
so the project does not list the extension's files one by one (Parcel puts
content hashes in their names). A "Copy Web Extension" build phase on the
extension target copies `../extension/dist-safari/` into the `.appex` instead.

## How it works for the user

1. The app's screen explains how to turn the extension on (Safari page menu →
   Manage Extensions, or Settings → Apps → Safari → Extensions).
2. On an article: page menu → **Langfour**. The reader replaces the page in
   the same tab, so Safari's Back button, or the reader's "‹ site" button,
   returns to it. Pages without an article show the reason in a new tab.
3. Tap a word: a bottom sheet with the translation and "Add to flashcards".
   Select a sentence: after a short pause its translation slides up.
4. Controls sit in a slim top bar ("‹ site", highlight toggle, Aa), because
   Safari owns the bottom of the screen; it hides while scrolling down. Aa
   opens display settings (size, theme, New York / San Francisco, spacing)
   and the flashcards link, plus the account: language, Sign in or Log out.
   Settings are remembered; the theme follows dark mode until changed.
5. New words get a highlighter mark once the known-words list has loaded
   (the reader refreshes it from Supabase; the text shows unmarked until
   then). Saved words turn green.
6. Signed out, the reader still works as a clean reader and explains how to
   sign in. Sign-in uses the code from the email (see below).

## Build and run

1. Build the web extension:
   ```bash
   npm --prefix apps/extension run build:safari
   ```
2. Open `apps/safari/Langfour Reader.xcodeproj`, pick a simulator or your
   iPhone, and run the **Langfour Reader** scheme. Rebuild step 1 after any
   change to the extension; Xcode copies `dist-safari/` again on every build.

Xcode needs the iOS platform installed (Xcode → Settings → Components) even to
build for the simulator.

## UI test runner

`LangfourReaderUITests/StepRunnerUITests.swift` drives Settings and Safari
from a step list, which is how the flow above was checked in the simulator
(labels are those of a German simulator):

```bash
cd apps/safari
TEST_RUNNER_STEPS='safarifresh;url:https://es.wikipedia.org/wiki/Madrid;wait:3;tap:Seitenmenü;tapcontains:Langfour;wait:3;shot:popup' \
TEST_RUNNER_OUT=/tmp/langfour-ui \
xcodebuild test -project "Langfour Reader.xcodeproj" -scheme "Langfour Reader" \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:LangfourReaderUITests/StepRunnerUITests
```

The step syntax is documented at the top of the file. The popup's own content
is not in the accessibility tree, so taps inside it use `tapxy:`.

## Permissions

The Safari build has no `host_permissions`. Safari lists each one in Settings
as its own "Ask" entry, naming the Koyeb and Supabase hosts, which reads as
alarming and adds prompts. The extension does not need them:

- Supabase allows any origin.
- The API allows `safari-web-extension://<UUID>` origins
  (`SAFARI_EXTENSION_ORIGIN_REGEX` in `apps/api/app.py`, tested in
  `apps/api/test_cors.py`). **Translations and saving words in Safari need that
  API change deployed.**

The only page access is `activeTab`, granted when the user taps Langfour in
the page menu.

## Accounts and signing

- Simulator: no Apple account needed.
- Your own iPhone: add a free Apple ID in Xcode → Settings → Accounts and pick
  it as the Team for both targets. Free-team builds stop launching after 7
  days; run again from Xcode to renew.
- TestFlight / App Store: Apple Developer Program ($99/year).

The bundle identifiers are `com.langfour.reader` and
`com.langfour.reader.Extension`; change them if that ID is taken when you sign.

## Signing in

Safari on iOS cannot follow the magic link back into the extension, so the
sign-in page (opened from the reader) takes the code from the same email. Supabase only puts a
code in the email if the "Magic link or OTP" template contains `{{ .Token }}`.
Something like this, after the "Sign in" button (and change the footer's
"without this link" to "without this link or code"):

```html
<p style="margin:28px 0 8px; font-size:14px; line-height:1.6; color:#4b5563;">Or enter this code in the Langfour extension:</p>
<p style="margin:0; font-size:30px; line-height:1.2; font-weight:700; letter-spacing:6px; color:#111827; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;">{{ .Token }}</p>
```

The template is in the Supabase dashboard under Authentication → Emails →
Magic link or OTP. It is the production email, so the web app's sign-in emails
change too.
