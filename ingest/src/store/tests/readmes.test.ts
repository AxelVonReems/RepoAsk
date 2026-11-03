import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { initDB, db } from '../db.js';
import { upsertRepositories } from '../repository.js';
import { getReadmeEtag, toReadmeRecord, touchReadme, upsertReadme } from '../readmes.js';

describe('README Store: Upsert and Idempotency', () => {
  const MOCK_ID = '888888888';

  before(() => {
    initDB();
    db.prepare('DELETE FROM repositories WHERE id = ?').run(MOCK_ID);
    // readmes.repoId references repositories.id, so the parent row must exist
    upsertRepositories([{
      id: MOCK_ID,
      name: 'readme-demo',
      fullName: 'demo/readme-demo',
      url: 'https://github.com/demo/readme-demo',
      description: null,
      metric: 1,
      forks: 0,
      openIssues: 0,
      topics: [],
      syncedAt: new Date().toISOString()
    }]);
  });

  after(() => {
    // Cascade removes the README row as well
    db.prepare('DELETE FROM repositories WHERE id = ?').run(MOCK_ID);
  });

  test('should insert, detect unchanged content and update changed content', () => {
    assert.strictEqual(upsertReadme(toReadmeRecord(MOCK_ID, '# Demo', 'W/"v1"')), 'inserted');

    // Same content with a new ETag must not count as a change
    assert.strictEqual(upsertReadme(toReadmeRecord(MOCK_ID, '# Demo', 'W/"v2"')), 'unchanged');
    assert.strictEqual(getReadmeEtag(MOCK_ID), 'W/"v2"', 'Latest ETag should be stored');

    assert.strictEqual(upsertReadme(toReadmeRecord(MOCK_ID, '# Demo v2', 'W/"v3"')), 'updated');

    const rows = db.prepare('SELECT COUNT(*) as count FROM readmes WHERE repoId = ?').get(MOCK_ID) as { count: number };
    assert.strictEqual(rows.count, 1, 'Repeated upserts must never duplicate a README');
  });

  test('should compute sha256 and UTF-8 byte size', () => {
    const record = toReadmeRecord(MOCK_ID, 'héllo', null);

    assert.match(record.contentSha, /^[0-9a-f]{64}$/);
    assert.strictEqual(record.sizeBytes, 6, '"é" is 2 bytes in UTF-8');
  });

  test('should only bump fetchedAt on 304 touch', () => {
    const before = db.prepare('SELECT contentSha FROM readmes WHERE repoId = ?').get(MOCK_ID) as { contentSha: string };

    touchReadme(MOCK_ID, '2030-01-01T00:00:00.000Z');

    const after = db.prepare('SELECT contentSha, fetchedAt FROM readmes WHERE repoId = ?').get(MOCK_ID) as { contentSha: string; fetchedAt: string };
    assert.strictEqual(after.fetchedAt, '2030-01-01T00:00:00.000Z');
    assert.strictEqual(after.contentSha, before.contentSha, 'Content must be untouched');
  });

  test('should return null ETag for a repository without a stored README', () => {
    assert.strictEqual(getReadmeEtag('does-not-exist'), null);
  });
});
