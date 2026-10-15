const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

const express = require('express');
const theme = require('jsonresume-theme-straightforward');

const app = express();

const port = process.env.PORT || 3000;
const publicDir = path.join(__dirname, '..', 'public');

app.use(express.json());
app.use(express.static(publicDir));

// Renders the posted JSON Resume and stores the result in the public dir.
app.post('/resume', async (req, res, next) => {
  const resume = req.body;

  if (!resume || typeof resume !== 'object' || Array.isArray(resume)) {
    return res.status(400).json({ error: 'Request body must be a JSON Resume object.' });
  }

  try {
    const html = theme.render(resume);
    const filename = `${crypto
      .createHash('sha256')
      .update(JSON.stringify(resume))
      .digest('hex')
      .slice(0, 16)}.html`;

    await fs.mkdir(publicDir, { recursive: true });
    await fs.writeFile(path.join(publicDir, filename), html, 'utf8');

    res.status(201).json({ path: `/${filename}` });
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

if (require.main === module) {
  app.listen(port, () => {
    console.log(`json-resume-api listening on http://localhost:${port}`);
  });
}

module.exports = app;
