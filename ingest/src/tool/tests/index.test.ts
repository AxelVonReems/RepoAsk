import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import { initDB, db } from '../../store/db.js';
import { getTopRepositories } from '../index.js';

describe('AI Tool: Honest State', () => {
  before(() => {
    initDB();
    // Force an empty state for this specific test suite
    db.prepare('DELETE FROM repositories').run();
  });

  test('should handle empty database gracefully without crashing', () => {
    const result = getTopRepositories(5);

    assert.strictEqual(typeof result, 'string', 'Tool output must always be a string');
    assert.ok(result.length > 0, 'Tool output must not be entirely empty');

    // Assert getTopRepositories does not return undefined or throw an error.
    assert.notEqual(result, undefined, 'Result must be defined');
  });
});