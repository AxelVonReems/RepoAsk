// Resolves the SOURCE setting into the start URL and page limit for a sync run.
//   "search:<query>" -> /search/repositories, sorted by stars (desc)
//   "org:<name>"     -> /orgs/<name>/repos

export type SourceKind = 'search' | 'org';

export interface SyncSource {
  kind: SourceKind;
  url: string;
  maxPages: number;
}

const API = 'https://api.github.com';
const PER_PAGE = 100;

// The Search API never returns more than 1,000 results (10 pages of 100)
const SEARCH_MAX_PAGES = 10;

export function resolveSource(source: string, maxPages: number): SyncSource {
  const separator = source.indexOf(':');
  const kind = source.slice(0, separator);
  const value = source.slice(separator + 1).trim();

  if (separator === -1 || !value) {
    throw new Error(`Invalid SOURCE "${source}". Expected "search:<query>" or "org:<name>".`);
  }

  if (kind === 'search') {
    const params = new URLSearchParams({
      q: value,
      sort: 'stars',
      order: 'desc',
      per_page: String(PER_PAGE),
    });
    return {
      kind,
      url: `${API}/search/repositories?${params}`,
      maxPages: Math.min(maxPages, SEARCH_MAX_PAGES),
    };
  }

  if (kind === 'org') {
    return {
      kind,
      url: `${API}/orgs/${encodeURIComponent(value)}/repos?per_page=${PER_PAGE}`,
      maxPages,
    };
  }

  throw new Error(`Unknown SOURCE kind "${kind}". Expected "search" or "org".`);
}
