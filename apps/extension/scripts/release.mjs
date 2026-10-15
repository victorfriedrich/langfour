// Builds the extension from a clean dist/ and publishes the zip that the web
// app's /extension page links to.
//
//   SUPABASE_SERVICE_ROLE_KEY=... npm run release        # build + upload
//   npm run release -- --dry-run                         # build + zip only
//
// The zip goes to the public `releases` bucket twice: once at a fixed path the
// download button points at, and once under the manifest version so older
// builds stay available. Uploads need the service-role key; the bucket has no
// write policy, so nothing else can replace the file.
import { existsSync, readFileSync, rmSync, mkdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import zip from 'bestzip';

const root = fileURLToPath(new URL('..', import.meta.url));
const envFile = `${root}.env`;
if (existsSync(envFile)) process.loadEnvFile(envFile);

const dryRun = process.argv.includes('--dry-run');
const BUCKET = 'releases';
const LATEST = 'chrome/langfour-extension.zip';

function run(cmd, args, cwd = root) {
  const result = spawnSync(cmd, args, { cwd, stdio: 'inherit', shell: process.platform === 'win32' });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const supabaseUrl = process.env.REACT_APP_SUPABASE_URL;
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!dryRun && !serviceKey) {
  console.error('Set SUPABASE_SERVICE_ROLE_KEY to upload, or pass --dry-run.');
  process.exit(1);
}

// Parcel never cleans dist/, and stale pages there look like a working build.
rmSync(`${root}dist`, { recursive: true, force: true });
run('npm', ['run', 'build:store']);
for (const page of ['dist/manifest.json', 'dist/src/auth.html', 'dist/src/reader.html']) {
  if (!existsSync(`${root}${page}`)) {
    console.error(`Build is missing ${page}.`);
    process.exit(1);
  }
}

const { version } = JSON.parse(readFileSync(`${root}dist/manifest.json`, 'utf8'));
mkdirSync(`${root}build`, { recursive: true });
const zipPath = `${root}build/langfour-extension-${version}.zip`;
rmSync(zipPath, { force: true });
// Zip the contents of dist/ so manifest.json sits at the root of the archive.
// Through bestzip's API with an explicit cwd: run via npx, it zipped the
// package directory (sources, node_modules) instead.
await zip({ source: '*', destination: zipPath, cwd: `${root}dist` });
console.log(`Built ${zipPath}`);

if (dryRun) process.exit(0);

const body = readFileSync(zipPath);
for (const [path, maxAge] of [
  [LATEST, 300],
  [`chrome/v${version}/langfour-extension.zip`, 31536000],
]) {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      'Content-Type': 'application/zip',
      'Cache-Control': `max-age=${maxAge}`,
      'x-upsert': 'true',
    },
    body,
  });
  if (!response.ok) {
    console.error(`Upload of ${path} failed: ${response.status} ${await response.text()}`);
    process.exit(1);
  }
  console.log(`Published ${supabaseUrl}/storage/v1/object/public/${BUCKET}/${path}`);
}
