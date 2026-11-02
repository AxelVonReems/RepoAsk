import dotenv from 'dotenv';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

// Repo root (ingest/src -> ../..). .env and data/ live there, shared with the Python side,
// so paths must not depend on the directory npm is run from.
const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

dotenv.config({ path: path.join(ROOT_DIR, '.env'), quiet: true });

// Relative DB paths resolve against the repo root; ":memory:" is passed through as-is
const dbPath = process.env.DB_PATH || 'data/worker.db';

export const config = {
  github: {
    token: process.env.GITHUB_TOKEN || '',
    // "search:<query>" (sorted by stars) or "org:<name>"
    source: process.env.SOURCE || 'search:stars:>5000',
    maxPages: Number(process.env.MAX_PAGES) || 10,
    // Search API allows 30 requests/min; pause between pages to stay well under it
    searchPageDelayMs: Number(process.env.SEARCH_PAGE_DELAY_MS) || 2000,
  },
  db: {
    path: dbPath === ':memory:' ? dbPath : path.resolve(ROOT_DIR, dbPath),
  },
} as const;
