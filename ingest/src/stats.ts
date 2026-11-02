import { initDB, db } from './store/db.js';

initDB();

const stats = db.prepare(`
  SELECT
    COUNT(*) as totalRepos,
    ROUND(AVG(metric), 2) as avgStars,
    SUM(openIssues) as totalIssues
  FROM repositories
`).get();

const readmeStats = db.prepare(`
  SELECT
    COUNT(*) as totalReadmes,
    ROUND(AVG(sizeBytes)) as avgReadmeBytes,
    MAX(sizeBytes) as maxReadmeBytes,
    MAX(fetchedAt) as lastReadmeCheck
  FROM readmes
`).get();

console.log('Repository Store Statistics:');
console.log(JSON.stringify({ ...stats as object, ...readmeStats as object }, null, 2));
