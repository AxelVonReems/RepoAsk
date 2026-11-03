import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parsePage } from '../page.js';

const searchPage = JSON.parse(
  fs.readFileSync(new URL('./fixtures/search-page.json', import.meta.url), 'utf8')
);

describe('Sync Page: payload validation', () => {
  test('valid search payload passes and unwraps items', () => {
    const repos = parsePage('search', searchPage);

    assert.ok(repos, 'Valid fixture must pass validation');
    assert.strictEqual(repos.length, 2);
    assert.strictEqual(repos[0]?.full_name, 'facebook/react');
  });

  test('topics are parsed, and default to [] when the field is absent', () => {
    const repos = parsePage('search', searchPage);

    assert.deepStrictEqual(repos?.[0]?.topics, ['javascript', 'react', 'ui', 'frontend']);
    assert.deepStrictEqual(repos?.[1]?.topics, [], 'Fixture item without topics must still validate');
  });

  test('topics with a non-string entry fail validation', () => {
    const broken = structuredClone(searchPage);
    broken.items[0].topics = ['ok', 42];

    assert.strictEqual(parsePage('search', broken), null);
  });

  test('search payload missing the envelope fails', () => {
    // A plain array is the org shape, not the search shape
    assert.strictEqual(parsePage('search', searchPage.items), null);
  });

  test('search payload with a malformed repo fails', () => {
    const broken = structuredClone(searchPage);
    broken.items[0].stargazers_count = 'many';

    assert.strictEqual(parsePage('search', broken), null);
  });

  test('org payload still accepts a plain array', () => {
    const repos = parsePage('org', searchPage.items);

    assert.ok(repos);
    assert.strictEqual(repos.length, 2);
  });
});
