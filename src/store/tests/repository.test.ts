import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { initDB, db } from '../db.js';
import { upsertRepositories } from '../repository.js';
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
      syncedAt: new Date().toISOString()
    };

    // First Execution
    const firstSync = upsertRepositories([mockRepo]);
    assert.strictEqual(firstSync.inserted, 1, 'First run should insert exactly 1 row');
    assert.strictEqual(firstSync.updated, 0, 'First run should update 0 rows');

    // Mutate the entity (simulating a GitHub API update)
    mockRepo.metric = 500;
    mockRepo.syncedAt = new Date().toISOString();

    // Second Execution
    const secondSync = upsertRepositories([mockRepo]);
    assert.strictEqual(secondSync.inserted, 0, 'Second run should insert 0 rows (no duplicates)');
    assert.strictEqual(secondSync.updated, 1, 'Second run should update exactly 1 row');

    // Final Database Assertion
    const finalRecord = db.prepare('SELECT metric FROM repositories WHERE id = ?').get(MOCK_ID) as { metric: number };
    assert.strictEqual(finalRecord.metric, 500, 'Database should reflect the updated metric');
  });
});