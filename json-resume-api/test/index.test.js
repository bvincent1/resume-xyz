const assert = require('node:assert/strict');
const { once } = require('node:events');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { describe, it } = require('node:test');

const createApp = require('../src');

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
    certificates: [],
    skills: [],
    interests: [],
    meta: {},
  };
}

async function startApp(options = {}) {
  const publicDir = await fs.mkdtemp(path.join(os.tmpdir(), 'json-resume-api-test-'));
  const server = createApp({ ...options, publicDir }).listen(0);
  await once(server, 'listening');
  const { port } = server.address();

  return {
    baseUrl: `http://127.0.0.1:${port}`,
    publicDir,
    async close() {
      const closed = once(server, 'close');
      server.close();
      server.closeAllConnections?.();
      await closed;
      await fs.rm(publicDir, { recursive: true, force: true });
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

describe('POST /resume/html', () => {
  it('returns a path to a rendered HTML document', async () => {
    const resume = makeResume('html-ok');
    const app = await startApp();

    try {
      const response = await postJson(app.baseUrl, '/resume/html', resume);
      assert.equal(response.status, 201);

      const { path: filePath } = await response.json();
      assert.match(filePath, /^\/[a-f0-9]{16}\.html$/);

      const filename = filePath.slice(1);
      const html = await fs.readFile(path.join(app.publicDir, filename), 'utf8');
      assert.ok(html.startsWith('<!DOCTYPE html>'));
      assert.ok(html.includes(resume.basics.name));

      const fileResponse = await fetch(`${app.baseUrl}${filePath}`);
      assert.equal(fileResponse.status, 200);
      assert.match(fileResponse.headers.get('content-type'), /^text\/html/);
    } finally {
      await app.close();
    }
  });

  it('renders certificates between work and education', async () => {
    const resume = makeResume('certificates');
    resume.work = [{ name: 'Acme', position: 'Engineer', startDate: '2020-01' }];
    resume.education = [{ institution: 'Test University' }];
    resume.certificates = [
      {
        name: 'Project Management',
        issuer: 'Google Coursera',
        date: '2024-03-07',
        url: 'https://coursera.deuterium.dev',
      },
      {
        name: 'Advanced Data Engineering',
        issuer: 'Databricks',
        date: '2025-07-21',
      },
    ];
    const app = await startApp();

    try {
      const response = await postJson(app.baseUrl, '/resume/html', resume);
      assert.equal(response.status, 201);

      const { path: filePath } = await response.json();
      const html = await fs.readFile(
        path.join(app.publicDir, filePath.slice(1)),
        'utf8',
      );

      assert.ok(html.includes('Project Management'));
      assert.ok(html.includes('Google Coursera'));
      assert.ok(html.includes('https://coursera.deuterium.dev'));
      assert.ok(html.includes('Advanced Data Engineering'));
      assert.ok(html.includes('Databricks'));

      assert.ok(html.indexOf('Experience') < html.indexOf('Certificates'));
      assert.ok(html.indexOf('Certificates') < html.indexOf('Education'));
    } finally {
      await app.close();
    }
  });

  it('returns the same path for identical input without using puppeteer', async () => {
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

      await fs.access(path.join(app.publicDir, firstBody.path.slice(1)));
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

      const filename = filePath.slice(1);
      const pdf = await fs.readFile(path.join(app.publicDir, filename), 'utf8');
      assert.ok(pdf.startsWith('%PDF'));

      assert.equal(fakeBrowser.pages.length, 1);
      const [page] = fakeBrowser.pages;
      assert.ok(page.html.includes(resume.basics.name));
      assert.deepEqual(page.pdfOptions, {
        path: path.join(app.publicDir, filename),
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

      await fs.access(path.join(app.publicDir, firstBody.path.slice(1)));
      assert.equal(fakeBrowser.pages.length, 2);
      assert.ok(fakeBrowser.pages.every((page) => page.closed));
    } finally {
      await app.close();
    }
  });
});
