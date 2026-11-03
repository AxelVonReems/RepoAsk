import { db } from './db.js';
import type { RepositoryRecord } from './types.js';

export function upsertRepositories(repos: RepositoryRecord[]): { inserted: number; updated: number } {
  // We use a check statement to accurately differentiate inserts from updates, 
  // as SQLite's info.changes returns 1 for both on an upsert.
  const checkStmt = db.prepare<{ id: string }>('SELECT 1 FROM repositories WHERE id = @id');

  // SQLite has no array type, so topics are bound as a JSON string
  const upsertStmt = db.prepare<Omit<RepositoryRecord, 'topics'> & { topics: string }>(`
    INSERT INTO repositories (
      id, name, fullName, url, description, metric, forks, openIssues, topics, syncedAt
    ) VALUES (
      @id, @name, @fullName, @url, @description, @metric, @forks, @openIssues, @topics, @syncedAt
    )
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      fullName = excluded.fullName,
      url = excluded.url,
      description = excluded.description,
      metric = excluded.metric,
      forks = excluded.forks,
      openIssues = excluded.openIssues,
      topics = excluded.topics,
      syncedAt = excluded.syncedAt
  `);

  const transaction = db.transaction((repositories: RepositoryRecord[]) => {
    let inserted = 0;
    let updated = 0;

    for (const repo of repositories) {
      const exists = checkStmt.get({ id: repo.id }) !== undefined;

      upsertStmt.run({ ...repo, topics: JSON.stringify(repo.topics) });

      if (exists) {
        updated++;
      } else {
        inserted++;
      }
    }

    return { inserted, updated };
  });

  return transaction(repos);
}
// Deletes repositories not seen since the cutoff (e.g. dropped out of the top-N search).
// Their READMEs are removed by ON DELETE CASCADE. Returns the number of deleted rows.
export function deleteRepositoriesSyncedBefore(cutoff: string): number {
  return db.prepare('DELETE FROM repositories WHERE syncedAt < ?').run(cutoff).changes;
}
