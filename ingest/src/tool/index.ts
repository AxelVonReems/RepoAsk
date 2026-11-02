import { fileURLToPath } from 'node:url';
import process from 'node:process';
import { db, initDB } from '../store/db.js';
import type { RepositoryRow, ToolItem } from './types.js';

export function getTopRepositories(limit: number = 10): string {
  initDB();

  // Stale data fallback
  const lastSyncRow = db.prepare('SELECT MAX(syncedAt) as lastSync FROM repositories').get() as { lastSync: string | null };
  let warning = '';

  if (lastSyncRow.lastSync) {
    const hoursSinceSync = (Date.now() - new Date(lastSyncRow.lastSync).getTime()) / (1000 * 60 * 60);
    if (hoursSinceSync > 24) {
      warning = 'WARNING: Data is older than 24 hours. Consider running a sync.\n\n';
    }
  }

  const stmt = db.prepare<[number], RepositoryRow>(`
    SELECT name, url, description, metric, syncedAt
    FROM repositories
    ORDER BY metric DESC
    LIMIT ?
  `);

  const rows = stmt.all(limit);

  if (rows.length === 0) {
    return "No repositories found in local cache. Please run the sync process first.";
  }

  const items: ToolItem[] = rows.map((row) => ({
    name: row.name,
    url: row.url,
    description: row.description,
    stars: row.metric,
    last_sync: row.syncedAt
  }));

  // Return JSON string without spacing
  return warning + JSON.stringify(items);
}

// Self-executing test block
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  console.log(getTopRepositories(3));
}