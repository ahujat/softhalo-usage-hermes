# Soft Halo Usage for Hermes Agent

**Shows your Hermes token usage in Soft Halo's always-on-top overlay, next to Claude Code and your other AI tools.** This plugin records usage numbers to a local folder; the Soft Halo desktop app reads them.

Status: 0.1.0. Tested in WSL with Hermes v0.23.1 (13 November 2026) and v0.13.0 (12 November), recording OpenRouter calls that Soft Halo 2.0.5.20 showed; passes `hermes plugins validate` on v0.23.1. Hermes versions without the `post_auxiliary_call` hook (v0.13.0 has none) do not count side calls such as title generation; Hermes logs a warning about the unknown hook and carries on.

## Requirements

- Hermes Agent with observer hooks (`post_api_request`, `post_auxiliary_call`).
- **Windows** (Hermes on Windows itself or in WSL), with **Soft Halo for Windows 2.0.5.20 or later**. Without it, the plugin only writes small files that nothing reads.

Soft Halo with AI usage is in beta: get the signed 2.0.5.22 build from the [beta page](https://softhalo.app/download/beta-20522-3535fbf8dac88ffa) (SHA-256 `5985046EDE0CD2774BA35101B583A6E18E32FDC24D7E49253D0F8E5258086E45`, also in [SHA256SUMS.txt](https://softhalo.app/downloads/windows/beta-2.0.5.22-5985046ede0cd277/SHA256SUMS.txt)).

## Install

1. Copy this folder to `~/.hermes/plugins/softhalo-usage/` (for a named profile, that profile's `plugins` folder).
2. Enable it in `~/.hermes/config.yaml`:
   ```yaml
   plugins:
     enabled:
       - softhalo-usage
   ```
3. Start a new Hermes session.

## What it records

After each provider request, one small file with:

- token counts: uncached input, cache reads, cache writes, output, and reasoning as part of output (Hermes already reports them separately)
- the provider and model, the session id, and Hermes's request id (so a request delivered twice is counted once)
- whether it was a main-loop request, a delegated subagent's, or an auxiliary call such as titling or compression
- the time and local date it finished

Auxiliary calls that fail or stream report no usage; they are recorded as requests without usage, not as zero. A Hermes request to Anthropic or OpenAI counts as Hermes usage, never as Claude Code's or Codex's, and never against their plan limits.

It never records prompts, responses, messages or tool output, even though the hook payloads include them. Your Hermes profile is identified only by a one-way hash of its folder.

## Files this plugin writes and reads

It writes one file per request into Soft Halo's inbox, and nothing else:

- `%LOCALAPPDATA%\Softhalo\usage\inbox\hermes-<session>-<time>-<process>-<random>.json`

Each file is written as `.tmp` and renamed when whole, so Soft Halo never reads half a file. Soft Halo deletes it after storing it. While Soft Halo reports its inbox full (`inbox\.full`), the plugin writes nothing and keeps a count in `%LOCALAPPDATA%\Softhalo\usage\hermes-dropped.json`, which the next file reports so Soft Halo can show the gap.

### In WSL

When Hermes runs inside WSL on the same Windows PC, the plugin writes to the same Windows folder, through the C: drive mount: `/mnt/c/Users/<Windows user>/AppData/Local/Softhalo/usage/`. It finds the Windows user by looking for an `AppData/Local/Softhalo` folder under `/mnt/c/Users`. If exactly one user has one, it uses that. If several do, it uses the one whose name matches your Linux user name. If it finds none, it writes nothing. If your C: drive is mounted elsewhere, or the names differ, set `SOFTHALO_USAGE_DIR` to the folder, for example `/mnt/c/Users/Ann/AppData/Local/Softhalo/usage`. `SOFTHALO_USAGE_DIR` also overrides the folder on Windows.

It reads only that count file and checks whether `inbox\.full` exists.

## What it does not do

- No network requests. Nothing leaves your machine.
- No tools, commands or changes to how Hermes behaves. Its hooks are observers and return nothing.

## Development

```bash
python -m unittest discover -s tests
```

`python tests/make_fixture.py <folder>` writes this plugin's real output for Soft Halo's collector tests (`Fixtures/AiUsage/adapter-output`).

## Privacy

See [PRIVACY.md](PRIVACY.md).

## License

MIT. See [LICENSE](LICENSE).
