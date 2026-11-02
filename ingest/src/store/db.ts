import Database from 'better-sqlite3';
import type { Database as DatabaseInstance } from 'better-sqlite3';
import * as dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { config } from '../config.js';

dotenv.config();

const dbPath = config.db.path;

const dbDir = path.dirname(dbPath);
if (!fs.existsSync(dbDir)) {
  fs.mkdirSync(dbDir, { recursive: true });
}

export const db: DatabaseInstance = new Database(dbPath);

export function initDB(): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS repositories (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      fullName TEXT NOT NULL,
      url TEXT NOT NULL,
      description TEXT,
      metric INTEGER NOT NULL,
      forks INTEGER NOT NULL,
      openIssues INTEGER NOT NULL,
      syncedAt TEXT NOT NULL
    )
  `);

  // One README per repository. contentSha lets the indexer skip unchanged READMEs.
  db.exec(`
    CREATE TABLE IF NOT EXISTS readmes (
      repoId TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
      etag TEXT,
      content TEXT NOT NULL,
      contentSha TEXT NOT NULL,
      sizeBytes INTEGER NOT NULL,
      fetchedAt TEXT NOT NULL
    )
  `);
}