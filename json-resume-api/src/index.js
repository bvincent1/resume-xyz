const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const express = require('express');
const theme = require('../theme');

const app = express();

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

app.use(express.json());
app.use(express.static(publicDir));

// Renders the posted JSON Resume to a PDF and stores it in the public dir.
app.post('/resume', async (req, res, next) => {
  const resume = req.body;

  if (!resume || typeof resume !== 'object' || Array.isArray(resume)) {
    return res.status(400).json({ error: 'Request body must be a JSON Resume object.' });
  }

  let page;
  try {
    const html = theme.render(resume);
    const filename = `${crypto
      .createHash('sha256')
      .update(JSON.stringify(resume))
      .digest('hex')
      .slice(0, 16)}.pdf`;
    const filePath = path.join(publicDir, filename);

    await fs.mkdir(publicDir, { recursive: true });

    const browser = await getBrowser();
    page = await browser.newPage();
    await page.setContent(html, { waitUntil: 'load' });
    await page.pdf({ path: filePath, format: 'A4', printBackground: true });

    console.log({ path: `http://localhost:${port}/${filename}` });
    res.status(201).json({ path: `/${filename}` });
  } catch (err) {
    next(err);
  } finally {
    if (page) await page.close().catch(() => {});
  }
});

app.use((err, req, res, next) => {
  if (err.type === 'entity.parse.failed') {
    return res.status(400).json({ error: 'Request body must be valid JSON.' });
  }

  console.error(err);
  res.status(500).json({ error: 'Failed to render resume.' });
});

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
