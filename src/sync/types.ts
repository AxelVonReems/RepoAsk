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
});

export const GitHubPageSchema = z.array(GitHubRepoSchema);

export type GitHubRepoPayload = z.infer<typeof GitHubRepoSchema>;

// Sync summary contract
export interface SyncSummary {
  fetched: number;
  inserted: number;
  updated: number;
  skipped: number;
  errors: number;
  apiCalls: number;
  durationMs: number;
  capped: boolean;
}