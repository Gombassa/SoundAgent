# SoundAgent Tick — Cowork Task

Paste the prompt below into Cowork's `/schedule` UI.
Set the interval to match `tick_interval` in your config.yaml (default: 300s / 5 min).

---

## Prompt to schedule

```
Run one SoundAgent tick to ingest and process new audio files.

Working directory: C:\Users\robin\Documents\GitHub\SoundAgent

Steps:
1. Run this command using the Bash tool:
   .venv\Scripts\python.exe -m soundagent tick --config config.yaml

2. Read the tick report printed to stdout and the file at D:\SoundAgent\summary.json.

3. Report back concisely:
   - How many files were delivered and to which categories
   - Any errors or low-confidence classifications
   - Which source adapters were active
   - Total duration

4. If exit code is 1 (partial failure), clearly flag which files failed and why.

Required environment variables (set in Cowork task settings):
  ANTHROPIC_API_KEY=<your key>

Do not modify any files. Do not retry failed files — the next tick will pick them up.
```

---

## Cowork task settings

| Setting | Value |
|---|---|
| Schedule | Every 5 minutes (or match tick_interval) |
| Working directory | `C:\Users\robin\Documents\GitHub\SoundAgent` |
| Environment | `ANTHROPIC_API_KEY=sk-ant-...` |

## Notes

- The tick is idempotent — running it more frequently than new files arrive is safe (SHA-256 dedup skips known files)
- Exit 0 = clean; Exit 1 = partial failure (some files errored, others may have succeeded)
- Logs rotate at 5 MB × 5 files: `D:\SoundAgent\soundagent.log`
- Full structured results: `D:\SoundAgent\summary.json`
