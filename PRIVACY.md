# Privacy policy: Soft Halo Usage for Hermes Agent

Effective 9 November 2026.

## What the plugin collects

From Hermes's `post_api_request` and `post_auxiliary_call` hooks, and nothing else:

- token counts per provider request: uncached input, cache reads, cache writes, output and reasoning
- the provider and model, the day, and whether the request was a main-loop, subagent or auxiliary call
- the session id, the parent session id for subagents, Hermes's request id, and a one-way hash of the Hermes profile folder

It does not collect prompts, responses, messages, tool output, file contents, platform or sender details, account names, email addresses or credentials, although the hook payloads include some of them.

## How it is used

Each record is written to a folder on your own computer (`%LOCALAPPDATA%\Softhalo\usage\inbox` on Windows) so the Soft Halo desktop app can show your usage. The plugin makes no network requests. Nothing is sent to the developer, to Nous Research or to anyone else.

## How long it is kept

Soft Halo deletes each file as soon as it has stored it, and keeps its own history under its own settings. Uninstalling the plugin stops all writes, and you can delete the usage folder at any time.

## Children

The plugin is not directed at children under 18.

## Contact

Questions about privacy: email privacy@softhalo.app.
