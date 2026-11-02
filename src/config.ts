import 'dotenv/config';
import process from 'node:process';

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
    path: process.env.DB_PATH || './data/worker.db',
  },
} as const;
