# README.md



```bash
curl -X POST "https://opencode.ai/inference/openai/v1/chat/completions" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5.1",
    "messages": [{ "role": "user", "content": "Say hi" }]
  }'
```
