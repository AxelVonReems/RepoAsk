import { GitHubPageSchema, GitHubSearchPageSchema } from './types.js';
import type { GitHubRepoPayload } from './types.js';
import type { SourceKind } from './source.js';

// Validates one raw API page against the schema for its source and returns the repos.
// Returns null when the payload does not match, so the caller can count it as an error.
export function parsePage(kind: SourceKind, rawData: unknown): GitHubRepoPayload[] | null {
  if (kind === 'org') {
    const result = GitHubPageSchema.safeParse(rawData);
    return result.success ? result.data : null;
  }

  const result = GitHubSearchPageSchema.safeParse(rawData);
  if (!result.success) return null;

  // GitHub timed out part of the search; the page is still usable but may miss repos
  if (result.data.incomplete_results) {
    console.warn('Search API returned incomplete_results=true; some repositories may be missing.');
  }

  return result.data.items;
}
