import axios, { AxiosError } from 'axios';
import type { AxiosResponseHeaders, RawAxiosResponseHeaders } from 'axios';
import * as dotenv from 'dotenv';
import { config } from '../config.js';
import { interpretReadmeResponse, README_ACCEPT, README_ACCEPT_STATUS } from './readme.js';
import type { ReadmeResult } from './readme.js';

// Load environment variables
dotenv.config();

const token = config.github.token;

// Fail fast if token is missing
if (!token) {
  throw new Error('FATAL: GITHUB_TOKEN environment variable is missing.');
}

// Axios client configuration
const githubClient = axios.create({
  baseURL: 'https://api.github.com',
  // The Search API can take several seconds per page; 5s caused needless timeouts
  timeout: 15 * 1000,
  headers: {
    'Authorization': `Bearer ${token}`,
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'ai-automation-worker'
  }
});

// Utility to pause execution for a given number of milliseconds.
export const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

export interface FetchOptions {
  params?: Record<string, string | number | boolean>;
  headers?: Record<string, string>;
  // Non-2xx statuses that are expected answers (e.g. 304, 404) and must not throw
  acceptStatus?: number[];
  responseType?: 'json' | 'text';
}

// Wraps a GET request with exponential backoff and jitter.
// Handles HTTP 429 Rate Limits and 5xx Server Errors gracefully.
export async function fetchWithRetry<T>(
  url: string,
  options: FetchOptions = {},
  maxRetries: number = 3
): Promise<{ data: T; headers: AxiosResponseHeaders | RawAxiosResponseHeaders; status: number }> {
  let attempt = 0;
  const initialDelay = 0.5 * 1000;
  const acceptStatus = options.acceptStatus ?? [];

  while (true) {
    try {
      const response = await githubClient.get<T>(url, {
        ...(options.params && { params: options.params }),
        ...(options.headers && { headers: options.headers }),
        ...(options.responseType && { responseType: options.responseType }),
        validateStatus: (status) => (status >= 200 && status < 300) || acceptStatus.includes(status),
      });
      return {
        data: response.data,
        headers: response.headers,
        status: response.status
      };
    } catch (error: unknown) {
      if (axios.isAxiosError(error)) {
        const axiosError = error as AxiosError;
        const status = axiosError.response?.status;

        // 401 and 404 are strictly non-recoverable
        if (status === 401 || status === 404) {
          throw new Error(`Non-recoverable API Error (${status}) at ${url}: ${axiosError.message}`);
        }

        const headers = axiosError.response?.headers;

        const retryAfter = headers?.['retry-after'];
        const rateLimitRemaining = headers?.['x-ratelimit-remaining'];
        const rateLimitReset = headers?.['x-ratelimit-reset'];

        // A 403 is only a rate limit if quota is 0 OR GitHub explicitly tells us to retry
        const isRateLimited =
          status === 429 ||
          (status === 403 && (rateLimitRemaining === '0' || retryAfter !== undefined));

        const isServerError = status !== undefined && status >= 500 && status <= 599;

        // Network errors (!status) or identified recoverable HTTP states
        const isRecoverable = !status || isRateLimited || isServerError;

        if (isRecoverable && attempt < maxRetries) {
          attempt++;

          let waitTime = initialDelay * Math.pow(2, attempt) + Math.random() * 500;

          if (isRateLimited) {
            const retryAfterSeconds = Number(retryAfter);
            const resetAtSeconds = Number(rateLimitReset);

            if (Number.isFinite(retryAfterSeconds)) {
              waitTime = retryAfterSeconds * 1000;
            } else if (rateLimitRemaining === '0' && Number.isFinite(resetAtSeconds)) {
              waitTime = Math.max(0, resetAtSeconds * 1000 - Date.now()) + 1000;
            } else if (status === 429 || status === 403) {
              // Secondary rate limit without explicit reset information
              waitTime = Math.max(waitTime, 60_000);
            }
          }

          // No status means the request never got a response (timeout, connection reset)
          const reason = isRateLimited
            ? `Rate limited (${status})`
            : status
              ? `Server error (${status})`
              : `Network error (${axiosError.code ?? 'unknown'})`;

          console.warn(
            `[Attempt ${attempt}/${maxRetries}] ${reason}. ` +
            `Waiting ${Math.round(waitTime / 1000)}s before retry...`
          );

          await sleep(waitTime);
          continue;
        }
      }

      // Retries exhausted or unknown error
      throw new Error(
        `Fatal: Request to ${url} failed after ${attempt} retries. Reason: ${
          error instanceof Error ? error.message : String(error)
        }`
      );
    }
  }
}

// Fetches a repository README. Sends the stored ETag so unchanged READMEs come back as 304.
export async function fetchReadme(fullName: string, etag: string | null): Promise<ReadmeResult> {
  const { data, headers, status } = await fetchWithRetry<unknown>(`/repos/${fullName}/readme`, {
    headers: {
      Accept: README_ACCEPT,
      ...(etag && { 'If-None-Match': etag }),
    },
    acceptStatus: README_ACCEPT_STATUS,
    responseType: 'text',
  });

  return interpretReadmeResponse(status, data, headers);
}

// Parses the GitHub REST API 'Link' header to extract the pagination URL for the next page.
export function parseNextPageUrl(linkHeader?: string): string | null {
  if (!linkHeader) return null;

  const links = linkHeader.split(',');

  for (const link of links) {
    // Match the URL inside the angle brackets and the rel="next" directive
    const match = link.match(/<([^>]+)>;\s*rel="next"/);
    if (match && match[1]) {
      return match[1];
    }
  }

  return null;
}