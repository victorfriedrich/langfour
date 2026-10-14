// Saves the pages listed in test/reader-corpus/urls.txt as headless Chrome
// renders them, into .corpus-cache/ (gitignored). The reader extracts from
// the rendered page in the user's browser, cookie banners and lazy content
// included, so a plain HTTP fetch would test something else.
//
//   node scripts/fetch-reader-corpus.mjs            fetch pages not cached yet
//   node scripts/fetch-reader-corpus.mjs --refresh  fetch everything again
//
// Then `npm run test:corpus` checks the extraction against every cached page.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const cacheDir = join(root, '.corpus-cache');
const refresh = process.argv.includes('--refresh');
const CHROME = process.env.CHROME_PATH
  ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
// A phone, like the Safari build; sites serve their mobile markup to it.
const USER_AGENT =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';

const entries = readFileSync(join(root, 'test/reader-corpus/urls.txt'), 'utf8')
  .split('\n')
  .map((line) => line.trim())
  .filter((line) => line && !line.startsWith('#'))
  .map((line) => {
    const [name, language, url] = line.split(/\s+/);
    return { name, language, url };
  });

mkdirSync(cacheDir, { recursive: true });
// A throwaway profile, so nothing touches the user's own Chrome profile.
const profile = join(tmpdir(), `reader-corpus-profile-${process.pid}`);

let fetched = 0;
for (const { name, url } of entries) {
  const file = join(cacheDir, `${name}.html`);
  if (existsSync(file) && !refresh) continue;
  const result = spawnSync(CHROME, [
    '--headless=new',
    '--disable-gpu',
    `--user-data-dir=${profile}`,
    `--user-agent=${USER_AGENT}`,
    '--window-size=402,874',
    '--virtual-time-budget=10000',
    '--dump-dom',
    url,
  ], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 60_000 });
  if (result.status !== 0 || !result.stdout.includes('<body')) {
    console.error(`${name}: failed (${result.error?.message ?? result.stderr.split('\n')[0]})`);
    continue;
  }
  // The page's address, for resolving relative links and images later.
  writeFileSync(file, `<!-- corpus-url: ${url} -->\n${result.stdout}`);
  fetched++;
  console.log(`${name}: ${(result.stdout.length / 1024).toFixed(0)} KB`);
}
rmSync(profile, { recursive: true, force: true });
console.log(`Fetched ${fetched}; ${entries.length} pages in the corpus.`);
