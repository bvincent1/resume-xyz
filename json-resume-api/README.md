# json resume api service

Renders a JSON Resume object to a PDF or an HTML document and returns a path to the generated file.

## Endpoints

- `POST /resume/pdf` — writes `<hash>.pdf` under `public/` and returns `{ "path": "/<hash>.pdf" }`.
- `POST /resume/html` — writes `<hash>.html` under `public/` and returns `{ "path": "/<hash>.html" }`.

Both files are served statically from `public/`.

## Example

```bash
curl --json @../application_manager/application_manager/supporting_documents/json-resume.json localhost:3000/resume/pdf | jq .
curl --json @../application_manager/application_manager/supporting_documents/json-resume.json localhost:3000/resume/html | jq .
```

## Tests

```bash
pnpm test
```
