import 'dotenv/config';
import process from 'node:process';

export const config = {
  github: {
    token: process.env.GITHUB_TOKEN || '',
    syncUrl: process.env.GITHUB_SYNC_URL || 'https://api.github.com/orgs/microsoft/repos?per_page=100',
    maxPages: Number(process.env.MAX_PAGES) || 5,
  },
  db: {
    path: process.env.DB_PATH || './data/worker.db',
  },
} as const;