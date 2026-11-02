const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const express = require('express');
const theme = require('../theme');

const port = process.env.PORT || 3000;
const publicDir = path.join(__dirname, '..', 'public');

// puppeteer is ESM-only, so load it lazily from CommonJS.
let puppeteerPromise;
function getPuppeteer() {
  if (!puppeteerPromise) {
    puppeteerPromise = import('puppeteer').then((mod) => mod.default);
  }
  return puppeteerPromise;
}

let browserPromise;

// Launch the browser once and reuse it, relaunching it if the connection drops.
function getBrowser() {
  if (!browserPromise) {
    browserPromise = getPuppeteer()
      // --no-sandbox is required in environments without unprivileged user namespaces (e.g. containers).
      .then((puppeteer) =>
        puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] }),
      )
      .then((browser) => {
        browser.once('disconnected', () => (browserPromise = undefined));
        return browser;
      });
    browserPromise.catch(() => (browserPromise = undefined));
  }
  return browserPromise;
}

// Validates the posted body, renders it, and derives the filename hash.
// Responds with a 400 and returns undefined when the body is not a JSON Resume object.
function renderResume(req, res) {
  const resume = req.body;

  if (!resume || typeof resume !== 'object' || Array.isArray(resume)) {
    res.status(400).json({ error: 'Request body must be a JSON Resume object.' });
    return;
  }

  return {
    html: theme.render(resume),
    hash: crypto
      .createHash('sha256')
      .update(JSON.stringify(resume))
      .digest('hex')
      .slice(0, 16),
  };
}

async function saveResume(extension, hash, write) {
  await fs.mkdir(publicDir, { recursive: true });
  const filename = `${hash}.${extension}`;
  await write(path.join(publicDir, filename));
  return filename;
}

function respondWithPath(res, filename) {
  console.log({ path: `http://localhost:${port}/${filename}` });
  res.status(201).json({ path: `/${filename}` });
}

function createApp({ getBrowser: getBrowserImpl = getBrowser } = {}) {
  const app = express();

  app.use(express.json());
  app.use(express.static(publicDir));

  // Renders the posted JSON Resume to a PDF and stores it in the public dir.
  app.post('/resume/pdf', async (req, res, next) => {
    let page;
    try {
      const rendered = renderResume(req, res);
      if (!rendered) return;

      const filename = await saveResume('pdf', rendered.hash, async (filePath) => {
        const browser = await getBrowserImpl();
        page = await browser.newPage();
        await page.setContent(rendered.html, { waitUntil: 'load' });
        await page.pdf({ path: filePath, format: 'A4', printBackground: true });
      });

      respondWithPath(res, filename);
    } catch (err) {
      next(err);
    } finally {
      if (page) await page.close().catch(() => {});
    }
  });

  // Writes the rendered JSON Resume HTML to the public dir.
  app.post('/resume/html', async (req, res, next) => {
    try {
      const rendered = renderResume(req, res);
      if (!rendered) return;

      const filename = await saveResume('html', rendered.hash, (filePath) =>
        fs.writeFile(filePath, rendered.html),
      );

      respondWithPath(res, filename);
    } catch (err) {
      next(err);
    }
  });

  app.use((err, req, res, next) => {
    if (err.type === 'entity.parse.failed') {
      return res.status(400).json({ error: 'Request body must be valid JSON.' });
    }

    console.error(err);
    res.status(500).json({ error: 'Failed to render resume.' });
  });

  return app;
}

const app = createApp();

if (require.main === module) {
  const server = app.listen(port, () => {
    console.log(`json-resume-api listening on http://localhost:${port}`);
  });

  const shutdown = async () => {
    server.close();
    if (browserPromise) {
      const browser = await browserPromise.catch(() => undefined);
      if (browser) await browser.close();
    }
    process.exit(0);
  };

  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}

module.exports = app;
module.exports.createApp = createApp;
