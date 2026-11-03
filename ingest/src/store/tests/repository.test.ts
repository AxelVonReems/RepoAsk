import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import Database from 'better-sqlite3';
import { addColumnIfMissing, initDB, db } from '../db.js';
import { deleteRepositoriesSyncedBefore, upsertRepositories } from '../repository.js';
import { toReadmeRecord, upsertReadme } from '../readmes.js';
import type { RepositoryRecord } from '../types.js';

describe('Repository Store: Upsert and Idempotency', () => {
  const MOCK_ID = '999999999';

  before(() => {
    initDB();
    // Clean up any potential artifacts before running
    db.prepare('DELETE FROM repositories WHERE id = ?').run(MOCK_ID);
  });

  after(() => {
    // Restore the database to a clean state after the test
    db.prepare('DELETE FROM repositories WHERE id = ?').run(MOCK_ID);
  });

  test('should correctly INSERT a new repository and UPDATE an existing one', () => {
    const mockRepo: RepositoryRecord = {
      id: MOCK_ID,
      name: 'demo-repo',
      fullName: 'microsoft/demo-repo',
      url: 'https://github.com/microsoft/demo-repo',
      description: 'A repository used for upsert demonstration',
      metric: 150,
      forks: 10,
      openIssues: 0,
      topics: ['demo', 'upsert'],
      syncedAt: new Date().toISOString()
    };

    // First Execution
    const firstSync = upsertRepositories([mockRepo]);
    assert.strictEqual(firstSync.inserted, 1, 'First run should insert exactly 1 row');
    assert.strictEqual(firstSync.updated, 0, 'First run should update 0 rows');

    // Mutate the entity (simulating a GitHub API update)
    mockRepo.metric = 500;
    mockRepo.topics = ['demo', 'upsert', 'llm'];
    mockRepo.syncedAt = new Date().toISOString();

    // Second Execution
    const secondSync = upsertRepositories([mockRepo]);
    assert.strictEqual(secondSync.inserted, 0, 'Second run should insert 0 rows (no duplicates)');
    assert.strictEqual(secondSync.updated, 1, 'Second run should update exactly 1 row');

    // Final Database Assertion
    const finalRecord = db.prepare('SELECT metric, topics FROM repositories WHERE id = ?').get(MOCK_ID) as { metric: number; topics: string };
    assert.strictEqual(finalRecord.metric, 500, 'Database should reflect the updated metric');
    assert.deepStrictEqual(JSON.parse(finalRecord.topics), ['demo', 'upsert', 'llm'], 'Topics should be stored as a JSON array and updated');
  });
});

describe('Repository Store: Schema Migration', () => {
  test('should add the topics column to a database created before it existed', () => {
    const legacy = new Database(':memory:');
    legacy.exec(`
      CREATE TABLE repositories (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, fullName TEXT NOT NULL, url TEXT NOT NULL,
        description TEXT, metric INTEGER NOT NULL, forks INTEGER NOT NULL,
        openIssues INTEGER NOT NULL, syncedAt TEXT NOT NULL
      )
    `);
    legacy.prepare(`INSERT INTO repositories VALUES ('1', 'old', 'o/old', 'u', NULL, 1, 0, 0, 't')`).run();

    addColumnIfMissing('repositories', 'topics', "TEXT NOT NULL DEFAULT '[]'", legacy);
    addColumnIfMissing('repositories', 'topics', "TEXT NOT NULL DEFAULT '[]'", legacy); // idempotent

    const row = legacy.prepare('SELECT topics FROM repositories WHERE id = ?').get('1') as { topics: string };
    assert.strictEqual(row.topics, '[]', 'Existing rows get the default');
    legacy.close();
  });
});
describe('Repository Store: Stale Cleanup', () => {
  const OLD_ID = '777777771';
  const NEW_ID = '777777772';
  const CUTOFF = '2026-01-01T00:00:00.000Z';

  const makeRepo = (id: string, syncedAt: string): RepositoryRecord => ({
    id,
    name: `repo-${id}`,
    fullName: `demo/repo-${id}`,
    url: `https://github.com/demo/repo-${id}`,
    description: null,
    metric: 1,
    forks: 0,
    openIssues: 0,
    topics: [],
    syncedAt
  });

  before(() => {
    initDB();
    db.prepare('DELETE FROM repositories WHERE id IN (?, ?)').run(OLD_ID, NEW_ID);
  });

  after(() => {
    db.prepare('DELETE FROM repositories WHERE id IN (?, ?)').run(OLD_ID, NEW_ID);
  });

  test('should delete repos not seen since the cutoff and cascade to their READMEs', () => {
    upsertRepositories([
      makeRepo(OLD_ID, '2025-12-31T23:59:59.000Z'),
      makeRepo(NEW_ID, CUTOFF)
    ]);
    upsertReadme(toReadmeRecord(OLD_ID, '# Old', null));

    const removed = deleteRepositoriesSyncedBefore(CUTOFF);

    assert.ok(removed >= 1, 'At least the stale mock repo should be removed');
    assert.strictEqual(db.prepare('SELECT 1 FROM repositories WHERE id = ?').get(OLD_ID), undefined, 'Stale repo must be deleted');
    assert.ok(db.prepare('SELECT 1 FROM repositories WHERE id = ?').get(NEW_ID), 'Repo synced at the cutoff must be kept');
    assert.strictEqual(db.prepare('SELECT 1 FROM readmes WHERE repoId = ?').get(OLD_ID), undefined, 'README must be removed by cascade');
  });
});
