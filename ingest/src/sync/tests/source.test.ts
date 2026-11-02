import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { resolveSource } from '../source.js';

describe('Sync Source: SOURCE resolution', () => {
  test('search source builds a stars-sorted search URL', () => {
    const source = resolveSource('search:stars:>5000', 5);
    const url = new URL(source.url);

    assert.strictEqual(source.kind, 'search');
    assert.strictEqual(url.pathname, '/search/repositories');
    assert.strictEqual(url.searchParams.get('q'), 'stars:>5000', 'Query must survive URL encoding');
    assert.strictEqual(url.searchParams.get('sort'), 'stars');
    assert.strictEqual(url.searchParams.get('order'), 'desc');
    assert.strictEqual(url.searchParams.get('per_page'), '100');
  });

  test('search source is capped at 10 pages (1,000 results)', () => {
    assert.strictEqual(resolveSource('search:stars:>5000', 50).maxPages, 10);
    assert.strictEqual(resolveSource('search:stars:>5000', 3).maxPages, 3);
  });

  test('org source keeps the org repos endpoint and page limit', () => {
    const source = resolveSource('org:microsoft', 50);

    assert.strictEqual(source.kind, 'org');
    assert.strictEqual(source.url, 'https://api.github.com/orgs/microsoft/repos?per_page=100');
    assert.strictEqual(source.maxPages, 50);
  });

  test('invalid sources fail fast', () => {
    assert.throws(() => resolveSource('stars:>5000', 10), /Unknown SOURCE kind/);
    assert.throws(() => resolveSource('search:', 10), /Invalid SOURCE/);
    assert.throws(() => resolveSource('microsoft', 10), /Invalid SOURCE/);
  });
});
