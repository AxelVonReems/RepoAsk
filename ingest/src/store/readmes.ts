import { createHash } from 'node:crypto';
import { db } from './db.js';
import type { ReadmeRecord, ReadmeUpsertResult } from './types.js';

// Builds a storable record from fetched README text
export function toReadmeRecord(repoId: string, content: string, etag: string | null): ReadmeRecord {
  return {
    repoId,
    etag,
    content,
    contentSha: createHash('sha256').update(content).digest('hex'),
    sizeBytes: Buffer.byteLength(content, 'utf8'),
    fetchedAt: new Date().toISOString(),
  };
}

// Stored ETag for a repository, sent as If-None-Match on the next sync
export function getReadmeEtag(repoId: string): string | null {
  const row = db.prepare<[string], { etag: string | null }>('SELECT etag FROM readmes WHERE repoId = ?').get(repoId);
  return row?.etag ?? null;
}

// Inserts or updates a README. 'unchanged' means same content (new ETag at most),
// so downstream indexing can skip it.
export function upsertReadme(readme: ReadmeRecord): ReadmeUpsertResult {
  const existing = db
    .prepare<[string], { contentSha: string }>('SELECT contentSha FROM readmes WHERE repoId = ?')
    .get(readme.repoId);

  db.prepare<ReadmeRecord>(`
    INSERT INTO readmes (repoId, etag, content, contentSha, sizeBytes, fetchedAt)
    VALUES (@repoId, @etag, @content, @contentSha, @sizeBytes, @fetchedAt)
    ON CONFLICT(repoId) DO UPDATE SET
      etag = excluded.etag,
      content = excluded.content,
      contentSha = excluded.contentSha,
      sizeBytes = excluded.sizeBytes,
      fetchedAt = excluded.fetchedAt
  `).run(readme);

  if (!existing) return 'inserted';
  return existing.contentSha === readme.contentSha ? 'unchanged' : 'updated';
}

// Records that a README was checked and GitHub answered 304 Not Modified
export function touchReadme(repoId: string, fetchedAt: string = new Date().toISOString()): void {
  db.prepare('UPDATE readmes SET fetchedAt = ? WHERE repoId = ?').run(fetchedAt, repoId);
}
