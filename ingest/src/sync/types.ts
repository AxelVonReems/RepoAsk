import { z } from 'zod';

// Runtime schema
export const GitHubRepoSchema = z.object({
  id: z.number(),
  name: z.string(),
  full_name: z.string(),
  html_url: z.string(),
  description: z.string().nullable().optional(),
  stargazers_count: z.number(),
  forks_count: z.number(),
  open_issues_count: z.number(),
  // Maintainer-chosen keywords; absent on some payloads, so default to none
  topics: z.array(z.string()).default([]),
});

// /orgs/{org}/repos returns a plain array
export const GitHubPageSchema = z.array(GitHubRepoSchema);

// /search/repositories wraps the array in an envelope
export const GitHubSearchPageSchema = z.object({
  total_count: z.number(),
  incomplete_results: z.boolean(),
  items: z.array(GitHubRepoSchema),
});

export type GitHubRepoPayload = z.infer<typeof GitHubRepoSchema>;

// Sync summary contract
export interface SyncSummary {
  fetched: number;
  inserted: number;
  updated: number;
  skipped: number;
  removed: number; // stale repos deleted after a clean run
  errors: number;
  apiCalls: number;
  durationMs: number;
  capped: boolean;
  readmes: {
    inserted: number;
    updated: number;
    unchanged: number;   // 200 with identical content
    notModified: number; // 304 via ETag
    missing: number;     // 404: repository has no README
    errors: number;
  };
}