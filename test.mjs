import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
const data = JSON.parse(readFileSync(new URL('./public/events.json', import.meta.url)));
test('all reactions resolve to a statement, with public sources', () => {
  const ids = new Set(data.statements.map(s => s.statement_id));
  assert.equal(ids.size, data.statements.length);
  assert(data.statements.length && data.reactions.length);
  for (const r of data.reactions) assert(ids.has(r.statement_id));
  for (const row of [...data.statements, ...data.reactions]) assert.equal(new URL(row.source_url).protocol, 'https:');
});
