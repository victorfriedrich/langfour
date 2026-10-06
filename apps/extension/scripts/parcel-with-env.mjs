// Runs Parcel with apps/extension/.env loaded into the environment.
//
// Parcel only reads .env from its project root, which it finds by walking up to
// the nearest lockfile. In this monorepo that is the repo root, so the
// extension's own .env was silently ignored and builds shipped without the
// Supabase URL ("supabaseUrl is required" at runtime). Variables already set in
// the shell still win, so CI can inject its own.
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const envFile = fileURLToPath(new URL('../.env', import.meta.url));
if (existsSync(envFile)) process.loadEnvFile(envFile);

const missing = ['REACT_APP_SUPABASE_URL', 'REACT_APP_SUPABASE_ANON_KEY'].filter((name) => !process.env[name]);
if (missing.length) {
  console.error(`Missing ${missing.join(', ')}. Copy .env.sample to .env and fill it in.`);
  process.exit(1);
}

const result = spawnSync('parcel', process.argv.slice(2), { stdio: 'inherit', shell: process.platform === 'win32' });
process.exit(result.status ?? 1);
