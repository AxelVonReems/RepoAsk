import type { AxiosResponseHeaders, RawAxiosResponseHeaders } from 'axios';

// Outcome of GET /repos/{owner}/{repo}/readme with a conditional request
export type ReadmeResult =
  | { status: 'fetched'; content: string; etag: string | null }
  | { status: 'not_modified' }
  | { status: 'missing' };

// Raw media type returns the Markdown itself instead of base64-encoded JSON
export const README_ACCEPT = 'application/vnd.github.raw+json';

// Statuses that are expected answers for a README request, not failures
export const README_ACCEPT_STATUS = [304, 404];

type Headers = AxiosResponseHeaders | RawAxiosResponseHeaders;

function headerValue(headers: Headers, name: string): string | null {
  const value = typeof headers.get === 'function' ? headers.get(name) : headers[name];
  return typeof value === 'string' ? value : null;
}

// Maps an HTTP response to a README outcome.
//   200 -> new or changed content (keep the ETag for the next run)
//   304 -> unchanged since the ETag we sent
//   404 -> the repository has no README; not an error
export function interpretReadmeResponse(status: number, data: unknown, headers: Headers): ReadmeResult {
  if (status === 304) return { status: 'not_modified' };
  if (status === 404) return { status: 'missing' };

  if (typeof data !== 'string') {
    throw new Error(`Expected raw README text, got ${typeof data}`);
  }

  return { status: 'fetched', content: data, etag: headerValue(headers, 'etag') };
}
