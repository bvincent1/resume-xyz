# Goal

Create a pipeline that combines job application information and ai to optimize resume data

## Tasks

- move current prompt creation into async tasks
- break out specific prompts into parent data that then feeds into child prompts

## Acceptance criteria

- uses pydantic_ai for prompting and tool management
- no dynamic or external configs, just functions inside task(s)
- ability to delegate simple / basic prompts to cheaper providers



