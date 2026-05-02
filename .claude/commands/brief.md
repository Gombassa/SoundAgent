Review available project context and produce a structured session briefing.

## What to read

1. **CLAUDE.md files** — repo-level and workspace-level, in that order.
2. **Memories** — any persisted user preferences, cross-project patterns, or workflow notes.
3. **Recent git log** — last 5–10 commits if in a repo context, to infer recent activity.
4. **Open files or tabs** — if visible in the current editor context.

## What to produce

A concise briefing covering:

1. **Project** — which repo/project this session is in, one-line summary of what it is.
2. **Current status** — what was last worked on, what state it's in (working / broken / in-progress).
3. **Open threads** — unresolved issues, pending decisions, known blockers.
4. **Next steps** — what was planned or implied as the next action.
5. **Constraints and preferences** — relevant environment limits, tooling quirks, output style notes.

## What NOT to include

- Resolved issues with no bearing on current work
- Full file contents or code dumps
- Anything speculative not grounded in the context read

## Steps

1. Read all available context sources above.
2. Synthesise into the briefing format — keep it scannable, no waffle.
3. End with a single question: "What are we working on today?" unless the open files or recent commits make the answer obvious, in which case propose it directly.
