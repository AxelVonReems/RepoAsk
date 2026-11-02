import { initDB, db } from './store/db.js';

initDB();

const stats = db.prepare(`
  SELECT 
    COUNT(*) as totalRepos, 
    ROUND(AVG(metric), 2) as avgStars, 
    SUM(openIssues) as totalIssues 
  FROM repositories
`).get();

console.log('Repository Store Statistics:');
console.log(JSON.stringify(stats, null, 2));