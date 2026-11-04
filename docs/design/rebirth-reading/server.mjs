import http from 'node:http';
import { readFile, writeFile, rename, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { createCatalog, getFeed, getHot } from './read-model.mjs';

const root = dirname(fileURLToPath(import.meta.url));

export async function startServer({ port = 4318, stateDir = join(tmpdir(), 'unspun-rebirth-reading') } = {}) {
  const [first, second, events] = await Promise.all(['event-materials.json', 'article-materials.json', 'events.json']
    .map(name => readFile(join(root, 'data', name), 'utf8').then(JSON.parse)));
  const catalog = createCatalog([...first, ...second], events);
  const validIds = new Set([...catalog.materials, ...catalog.events].map(item => item.id));
  await mkdir(stateDir, { recursive: true });
  const statePath = join(stateDir, 'feedback.json');
  let feedback = {};
  try { feedback = JSON.parse(await readFile(statePath, 'utf8')); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  let pendingWrite = Promise.resolve();

  const server = http.createServer(async (request, response) => {
    const send = (status, body, mime = 'application/json; charset=utf-8') => {
      response.writeHead(status, { 'Content-Type': mime, 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'" });
      response.end(mime.startsWith('application/json') ? JSON.stringify(body) : body);
    };
    try {
      const allowedHost = `127.0.0.1:${server.address().port}`;
      if (![allowedHost, `localhost:${server.address().port}`].includes(request.headers.host)) return send(403, { error: 'Invalid host' });
      const url = new URL(request.url, `http://${allowedHost}`);
      if (request.method === 'GET') {
        if (url.pathname === '/api/catalog') return send(200, { ...catalog, selections: undefined });
        if (url.pathname === '/api/feed') {
          try { return send(200, getFeed(catalog, url.searchParams.get('type') || 'all', url.searchParams.get('cursor') || '')); }
          catch (error) { return send(400, { error: error.message }); }
        }
        if (url.pathname === '/api/hot') return send(200, getHot(catalog));
        if (url.pathname === '/api/feedback') return send(200, feedback);
        const assets = { '/': ['index.html', 'text/html; charset=utf-8'], '/app.mjs': ['app.mjs', 'text/javascript; charset=utf-8'], '/style.css': ['style.css', 'text/css; charset=utf-8'] };
        const asset = assets[url.pathname];
        if (asset) return send(200, await readFile(join(root, asset[0])), asset[1]);
        return send(404, { error: 'Not found' });
      }
      if (request.method === 'POST' && url.pathname === '/api/feedback') {
        if (request.headers.origin !== `http://${request.headers.host}` ||
            !request.headers['content-type']?.startsWith('application/json')) return send(403, { error: 'Same-origin JSON required' });
        let body = '';
        for await (const part of request) {
          body += part;
          if (Buffer.byteLength(body) > 2048) return send(413, { error: 'Request too large' });
        }
        let change;
        try { change = JSON.parse(body); } catch { return send(400, { error: 'Invalid JSON' }); }
        if (!validIds.has(change.itemId) || ![null, 'worthwhile', 'unclear'].includes(change.value)) return send(400, { error: 'Invalid feedback' });
        const task = pendingWrite.then(async () => {
          const next = { ...feedback };
          if (change.value === null) delete next[change.itemId];
          else next[change.itemId] = { value: change.value, updatedAt: new Date().toISOString() };
          await writeFile(`${statePath}.tmp`, JSON.stringify(next, null, 2));
          await rename(`${statePath}.tmp`, statePath);
          feedback = next;
        });
        pendingWrite = task.catch(() => {});
        await task;
        return send(200, feedback);
      }
      return send(405, { error: 'Method not allowed' });
    } catch (error) {
      console.error('Preview request failed:', error.message);
      send(500, { error: 'Preview request failed' });
    }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  return { server, url: `http://127.0.0.1:${server.address().port}`, statePath };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const args = process.argv.slice(2);
  const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
  const { server, url } = await startServer({ port: Number(option('--port', '4318')), stateDir: option('--state-dir', undefined) });
  console.log(`Unspun reading preview: ${url}`);
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => server.close(() => process.exit(0)));
}
