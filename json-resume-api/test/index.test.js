const assert = require('node:assert/strict');
const { once } = require('node:events');
const fs = require('node:fs/promises');
const path = require('node:path');
const { afterEach, describe, it } = require('node:test');

const { createApp } = require('../src');

const publicDir = path.join(__dirname, '..', 'public');
const createdFiles = new Set();

function makeResume(label) {
  return {
    basics: {
      name: `Test ${label}`,
      label: 'Engineer',
      email: 'test@example.com',
      phone: '(912) 555-4321',
      url: 'https://example.com',
      summary: `Fixture ${label}`,
      location: { city: 'Austin', region: 'TX' },
      profiles: [],
    },
    work: [],
    volunteer: [],
    projects: [],
    education: [],
    publications: [],
    awards: [],
    skills: [],
    interests: [],
    meta: {},
  };
}

async function startApp(options = {}) {
  const server = createApp(options).listen(0);
  await once(server, 'listening');
  const { port } = server.address();

  return {
    baseUrl: `http://127.0.0.1:${port}`,
    async close() {
      const closed = once(server, 'close');
      server.close();
      server.closeAllConnections?.();
      await closed;
    },
  };
}

function postJson(baseUrl, endpoint, body) {
  return fetch(`${baseUrl}${endpoint}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function track(filePath) {
  const filename = filePath.replace(/^\//, '');
  createdFiles.add(filename);
  return filename;
}

function createFakeBrowser() {
  const pages = [];

  return {
    pages,
    async newPage() {
      const page = {
        closed: false,
        html: undefined,
        pdfOptions: undefined,
        async setContent(html) {
          page.html = html;
        },
        async pdf(options) {
          page.pdfOptions = options;
          await fs.writeFile(options.path, '%PDF-1.4\n% fake pdf\n');
        },
        async close() {
          page.closed = true;
        },
      };

      pages.push(page);
      return page;
    },
  };
}

afterEach(async () => {
  await Promise.all(
    [...createdFiles].map((filename) =>
      fs.rm(path.join(publicDir, filename), { force: true }),
    ),
  );
  createdFiles.clear();
});

describe('POST /resume/html', () => {
  it('returns a path to a rendered HTML document', async () => {
    const resume = makeResume('html-ok');
    const app = await startApp();

    try {
      const response = await postJson(app.baseUrl, '/resume/html', resume);
      assert.equal(response.status, 201);

      const { path: filePath } = await response.json();
      assert.match(filePath, /^\/[a-f0-9]{16}\.html$/);

      const filename = track(filePath);
      const html = await fs.readFile(path.join(publicDir, filename), 'utf8');
      assert.ok(html.startsWith('<!DOCTYPE html>'));
      assert.ok(html.includes(resume.basics.name));

      const fileResponse = await fetch(`${app.baseUrl}${filePath}`);
      assert.equal(fileResponse.status, 200);
      assert.match(fileResponse.headers.get('content-type'), /^text\/html/);
    } finally {
      await app.close();
    }
  });

  it('returns the same path for identical input without starting a browser', async () => {
    const resume = makeResume('html-idempotent');
    let browserCalls = 0;
    const app = await startApp({
      getBrowser: async () => {
        browserCalls += 1;
        throw new Error('browser should not be used for HTML rendering');
      },
    });

    try {
      const first = await postJson(app.baseUrl, '/resume/html', resume);
      const second = await postJson(app.baseUrl, '/resume/html', resume);

      assert.equal(first.status, 201);
      assert.equal(second.status, 201);

      const firstBody = await first.json();
      const secondBody = await second.json();

      assert.equal(firstBody.path, secondBody.path);
      track(firstBody.path);

      await fs.access(path.join(publicDir, firstBody.path.slice(1)));
      assert.equal(browserCalls, 0);
    } finally {
      await app.close();
    }
  });
});

describe('POST /resume/pdf', () => {
  it('returns a path to a generated PDF', async () => {
    const resume = makeResume('pdf-ok');
    const fakeBrowser = createFakeBrowser();
    const app = await startApp({ getBrowser: async () => fakeBrowser });

    try {
      const response = await postJson(app.baseUrl, '/resume/pdf', resume);
      assert.equal(response.status, 201);

      const { path: filePath } = await response.json();
      assert.match(filePath, /^\/[a-f0-9]{16}\.pdf$/);

      const filename = track(filePath);
      const pdf = await fs.readFile(path.join(publicDir, filename), 'utf8');
      assert.ok(pdf.startsWith('%PDF'));

      assert.equal(fakeBrowser.pages.length, 1);
      const [page] = fakeBrowser.pages;
      assert.ok(page.html.includes(resume.basics.name));
      assert.deepEqual(page.pdfOptions, {
        path: path.join(publicDir, filename),
        format: 'A4',
        printBackground: true,
      });
      assert.equal(page.closed, true);
    } finally {
      await app.close();
    }
  });

  it('returns the same path for identical input and closes each page', async () => {
    const resume = makeResume('pdf-idempotent');
    const fakeBrowser = createFakeBrowser();
    const app = await startApp({ getBrowser: async () => fakeBrowser });

    try {
      const first = await postJson(app.baseUrl, '/resume/pdf', resume);
      const second = await postJson(app.baseUrl, '/resume/pdf', resume);

      assert.equal(first.status, 201);
      assert.equal(second.status, 201);

      const firstBody = await first.json();
      const secondBody = await second.json();

      assert.equal(firstBody.path, secondBody.path);
      track(firstBody.path);

      await fs.access(path.join(publicDir, firstBody.path.slice(1)));
      assert.equal(fakeBrowser.pages.length, 2);
      assert.ok(fakeBrowser.pages.every((page) => page.closed));
    } finally {
      await app.close();
    }
  });
});
