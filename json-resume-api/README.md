# json resume api service

Runs the json-resume as a single post enpoint, and returns a path to the pdf file


## Example

```bash
curl --json @../application_manager/application_manager/supporting_documents/json-resume.json localhost:3000/resume | jq .
```
