import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import register, { invokeDiscovery } from './rig-memory-discovery.mjs';
import { loadExtensions, loadExtensionFromFactory, createExtensionRuntime } from '/home/adam/.nvm/versions/node/v22.23.2/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/loader.js';
import { createEventBus } from '/home/adam/.nvm/versions/node/v22.23.2/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/event-bus.js';

const source = dirname(fileURLToPath(import.meta.url));
const root = await mkdtemp(join(tmpdir(), 'rig-memory-native-'));
const digest = async path => createHash('sha256').update(await readFile(path)).digest('hex');
let controls = 0;
try {
  const helper = join(source, 'rig_memory_adapter.py');
  const db = join(root, 'fixture.db');
  const prepare = spawnSync('/usr/bin/python3', ['-B', '-c', `import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as c:
 c.execute('CREATE TABLE mem(id INTEGER PRIMARY KEY,text,tag,project,created_at)')
 c.execute("CREATE VIRTUAL TABLE mem_fts USING fts5(text,tag,project,content='mem',content_rowid='id')")
 c.executemany('INSERT INTO mem VALUES(?,?,?,?,?)',[(1,'Bríd CallMeIE '+'source body '*100,'fixture','urban','2026-10-03'),(2,'CallMeIE other hotel','fixture','hotel','2026-10-03')])
 c.execute("INSERT INTO mem_fts(mem_fts) VALUES('rebuild')")`, db], { encoding: 'utf8' });
  assert.equal(prepare.status, 0, prepare.stderr);
  const config = { helper, db, sha256: await digest(helper) };
  const factory = await loadExtensionFromFactory(pi => register(pi, config), root,
    createEventBus(), createExtensionRuntime(), join(source, 'rig-memory-discovery.mjs'));
  const tools = factory.tools;
  assert.deepEqual([...tools.keys()], ['rig_memory_discover', 'rig_memory_source']); controls++;
  const query = params => tools.get('rig_memory_discover').definition.execute('test', params);
  const fetch = params => tools.get('rig_memory_source').definition.execute('test', params);
  const normal = await query({ query: 'Bríd', project: 'urban' });
  assert.equal(normal.isError, false); assert.equal(normal.details.results[0].id, '1');
  assert.ok(normal.details.results[0].body.startsWith('Bríd')); controls++;
  const fetched = await fetch({ record_id: '1', project: 'urban' });
  assert.deepEqual(fetched.details.results[0], normal.details.results[0]); controls++;
  const empty = await query({ query: 'Bríd', project: 'hotel' });
  assert.equal(empty.isError, false); assert.equal(empty.details.status, 'empty'); controls++;
  const scope = await query({ query: 'CallMeIE', session: 'unknown' });
  assert.equal(scope.isError, true); assert.equal(scope.details.status, 'unsupported_scope'); controls++;
  const bounded = await query({ query: 'CallMeIE', body_budget: 10 });
  assert.equal(bounded.details.body_budget_exhausted, true);
  assert.ok(bounded.details.results.some(row => row.body_truncated)); controls++;
  const absent = await invokeDiscovery({ query: 'test' }, undefined, { ...config, db: join(root, 'missing.db') });
  assert.equal(absent.status, 'unavailable'); controls++;
  await assert.rejects(invokeDiscovery({ query: 'test' }, undefined, { ...config, sha256: '0'.repeat(64) }), /byte drift/); controls++;
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(invokeDiscovery({ query: 'test' }, aborted.signal, config), /cancelled/); controls++;
  const invalid = await query({ query: 'test', body_budget: 100001 });
  assert.equal(invalid.isError, true); assert.equal(invalid.details.status, 'unavailable'); controls++;
  const sleeper = join(root, 'sleep.py');
  await writeFile(sleeper, 'import time\ntime.sleep(30)\n');
  await assert.rejects(invokeDiscovery({ query: 'test' }, undefined,
    { ...config, helper: sleeper, sha256: await digest(sleeper), timeout_ms: 50 }), /timeout/); controls++;
  const bad = join(root, 'bad.py');
  await writeFile(bad, 'print("not json")\n');
  await assert.rejects(invokeDiscovery({ query: 'test' }, undefined,
    { ...config, helper: bad, sha256: await digest(bad) }), /invalid historical memory response/); controls++;
  // Load through the real installed Pi1.0.1 extension loader without altering
  // the active agent or invoking production database tools.
  const loaded = await loadExtensions([join(source, 'rig-memory-discovery.mjs')], root);
  assert.equal(loaded.errors.length, 0, JSON.stringify(loaded.errors));
  assert.equal(loaded.extensions.length, 1);
  assert.deepEqual([...loaded.extensions[0].tools.keys()], ['rig_memory_discover', 'rig_memory_source']); controls++;
  console.log(JSON.stringify({ schema: 'rig-memory-native-fixture/v1', controls,
    status: 'passed', pi_version: '1.0.1', helper_sha256: config.sha256,
    extension_sha256: await digest(join(source, 'rig-memory-discovery.mjs')),
    production_db_invoked: false, active_pi_modified: false }));
} finally {
  await rm(root, { recursive: true, force: true });
}
