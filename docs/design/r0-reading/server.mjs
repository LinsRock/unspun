import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const directory = fileURLToPath(new URL('.', import.meta.url));
const research = resolve(directory, '../../research/r0-2026-10-15');
const port = Number(process.env.R0_PREVIEW_PORT || 4178);
const files = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/model.mjs', ['model.mjs', 'text/javascript; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/data/manifest.json', ['manifest.json', 'application/json; charset=utf-8']],
  ['/data/candidates.json', [resolve(research, 'candidates.json'), 'application/json; charset=utf-8']],
  ['/evidence/observations.json', [resolve(research, 'observations.json'), 'application/json; charset=utf-8']],
  ['/evidence/source-validation.md', [resolve(research, '../2026-10-15-r0-source-validation.md'), 'text/plain; charset=utf-8']],
]);
const server = createServer(async (request, response) => {
  response.setHeader('Cache-Control', 'no-store');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.setHeader('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    response.writeHead(405, { Allow: 'GET, HEAD' }).end();
    return;
  }
  const pathname = new URL(request.url, 'http://localhost').pathname;
  try {
    let data;
    let contentType = 'application/json; charset=utf-8';
    if (pathname === '/data/materials.json') {
      try { data = await readFile(resolve(directory, 'materials.local.json')); }
      catch (error) {
        if (error.code !== 'ENOENT') throw error;
        data = JSON.stringify({ schema_version: 'unspun-r0-local-materials-v1', materials: {}, archive_available: false });
      }
    } else if (pathname === '/data/fingerprint.json') {
      data = JSON.stringify({ sha256: createHash('sha256').update(await readFile(resolve(research, 'candidates.json'))).digest('hex') });
    } else {
      const entry = files.get(pathname);
      if (!entry) { response.writeHead(404).end('Not found'); return; }
      contentType = entry[1];
      data = await readFile(resolve(directory, entry[0]));
    }
    response.writeHead(200, { 'Content-Type': contentType });
    response.end(request.method === 'HEAD' ? undefined : data);
  } catch (error) {
    console.error('Preview request failed:', pathname, error.code || error.message);
    response.writeHead(500).end('Preview resource unavailable');
  }
});
server.listen(port, '127.0.0.1', () => console.log(`Unspun R0 preview: http://127.0.0.1:${port}`));
