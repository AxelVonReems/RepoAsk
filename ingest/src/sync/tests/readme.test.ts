import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { interpretReadmeResponse } from '../readme.js';

describe('Sync README: response interpretation', () => {
  test('200 returns content and ETag', () => {
    const result = interpretReadmeResponse(200, '# Hello', { etag: 'W/"abc"' });

    assert.deepStrictEqual(result, { status: 'fetched', content: '# Hello', etag: 'W/"abc"' });
  });

  test('200 without ETag still returns content', () => {
    const result = interpretReadmeResponse(200, '# Hello', {});

    assert.deepStrictEqual(result, { status: 'fetched', content: '# Hello', etag: null });
  });

  test('304 means unchanged since the stored ETag', () => {
    assert.deepStrictEqual(interpretReadmeResponse(304, '', {}), { status: 'not_modified' });
  });

  test('404 means no README and is skipped, not an error', () => {
    assert.deepStrictEqual(interpretReadmeResponse(404, '{"message":"Not Found"}', {}), { status: 'missing' });
  });

  test('200 with non-text body is rejected', () => {
    assert.throws(() => interpretReadmeResponse(200, { content: 'base64...' }, {}), /Expected raw README text/);
  });
});
