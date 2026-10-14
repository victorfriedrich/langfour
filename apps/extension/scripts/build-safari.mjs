// Builds the Safari (iOS) variant into dist-safari/: the article reader only.
//
// The Xcode project in apps/safari references dist-safari/ rather than copying
// it, so rebuilding here and re-running the app in Xcode picks up changes.
//
// Parcel's webextension transformer only accepts a file named manifest.json,
// so instead of a second source manifest this builds the normal one and then
// trims the *built* manifest, whose paths Parcel has already resolved:
//   - drops the subtitle content script and its web-accessible files. The
//     reader injects the content script itself (activeTab + scripting) on
//     the page the user asks to read, so no site needs it up front, and iOS
//     does not ask for access to Netflix, YouTube or Prime Video;
//   - renames it "Langfour Reader" and drops host_permissions (see below);
//   - drops the popup: a tap on Langfour opens the reader directly
//     (chrome.action.onClicked in backgroundScript.ts);
//   - drops `key` (Chrome's fixed extension ID; Safari ignores it) and
//     `commands` (iOS Safari has no keyboard shortcuts);
//   - drops the chrome-extension://*/* web_accessible_resources entry, which
//     only exists so Parcel builds auth.html and reader.html (see
//     langfive-extension-build-gotchas) and is not a valid Safari match
//     pattern. Pages opened with tabs.create do not need to be web-accessible.
import { readFileSync, rmSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const outDir = 'dist-safari';
const SUBTITLE_HOSTS = ['www.netflix.com', 'www.youtube.com', 'www.primevideo.com'];

// Parcel never cleans its output directory, so stale pages would survive. Its
// cache has to go too: with the output deleted but the cache kept, Parcel
// reports every bundle as built yet writes none of them.
rmSync(new URL(`../${outDir}`, import.meta.url), { recursive: true, force: true });
rmSync(new URL('../.parcel-cache-safari', import.meta.url), { recursive: true, force: true });

const build = spawnSync(
  'node',
  [
    'scripts/parcel-with-env.mjs',
    'build',
    'manifest.json',
    '--config',
    '@parcel/config-webextension',
    '--no-scope-hoist',
    '--no-source-maps',
    '--dist-dir',
    outDir,
    '--cache-dir',
    '.parcel-cache-safari',
  ],
  {
    cwd: root,
    stdio: 'inherit',
    shell: process.platform === 'win32',
    // Read as process.env.EXTENSION_TARGET, which Parcel inlines at build time.
    env: { ...process.env, EXTENSION_TARGET: 'safari' },
  },
);
if (build.status !== 0) process.exit(build.status ?? 1);

const manifestPath = new URL(`../${outDir}/manifest.json`, import.meta.url);
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const isSubtitleHost = (pattern) => SUBTITLE_HOSTS.some((host) => pattern.includes(host));

delete manifest.key;
delete manifest.commands;
const notSubtitleSite = (entry) => !entry.matches.some(isSubtitleHost);
manifest.content_scripts = (manifest.content_scripts ?? []).filter(notSubtitleSite);
manifest.web_accessible_resources = (manifest.web_accessible_resources ?? [])
  .filter(notSubtitleSite)
  .filter((entry) => !entry.matches.some((pattern) => pattern.startsWith('chrome-extension://')));
manifest.name = 'Langfour Reader';
manifest.short_name = 'Langfour';
manifest.description =
  'Read any article in a clean reader, translate words and save them to your Langfour flashcards.';
// No popup: a tap on Langfour opens the reader (chrome.action.onClicked in
// backgroundScript.ts). Account and language settings are in the reader.
const { default_popup: _popup, ...action } = manifest.action;
manifest.action = { ...action, default_title: 'Langfour' };
// Safari puts every host permission in front of the user as its own
// "Ask"/"Allow" entry, listing the Koyeb and Supabase hostnames. The
// extension does not need them: Supabase answers any origin, and the API
// allows safari-web-extension:// origins (apps/api/app.py), since it
// authenticates with bearer tokens rather than cookies.
delete manifest.host_permissions;

writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

for (const unused of ['images']) {
  rmSync(new URL(`../${outDir}/${unused}`, import.meta.url), { recursive: true, force: true });
}

for (const page of ['src/reader.html', 'src/auth.html', 'src/contentScript.js', 'src/index.js', 'src/index.css']) {
  try {
    readFileSync(new URL(`../${outDir}/${page}`, import.meta.url));
  } catch {
    console.error(`Safari build is missing ${page}.`);
    process.exit(1);
  }
}
console.log(`Safari build ready in ${outDir}/`);
