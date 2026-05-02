Generate a ready-to-paste Cowork task prompt for the SoundAgent tick.

Read cowork_task.md in the repo root and print the prompt block from it, then remind
the user of the three Cowork task settings (schedule interval, working directory,
ANTHROPIC_API_KEY env var).

If the user provides an argument (e.g. "/schedule 10min"), override the default
5-minute interval with the one they specified.

Keep the response short — just the prompt block and the settings table.
