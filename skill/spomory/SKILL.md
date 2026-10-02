---
name: spomory
description: >-
  Use whenever Spomory's memory tools (add_memory, search_memory,
  forget_memory, forget_all_memory, get_graph, export_memory) are
  available as MCP tools. Teaches recalling relevant memory before
  assuming you don't know something about the user or project, and
  saving durable facts as they come up -- Spomory's tools are purely
  reactive on their own and do nothing unless something actively calls
  them.
---

# Use Spomory's memory proactively

Spomory gives you a memory graph that persists across sessions and is
shared across every client connected to the same account. The tools
exist, but nothing calls them automatically -- that's this skill's job.

## Recall first

At the start of a task, before asking the user something you might
already know, or before assuming you're starting from zero: call
`search_memory` with the relevant nouns (project name, person's name,
technology, topic). A query costs nothing if it comes back empty --
not calling it costs the user re-explaining something they already told
you, possibly through a different client.

If this is clearly a brand-new account (search comes back with no
results at all, on what looks like the first real exchange), it's worth
asking a few lightweight questions instead of silently starting cold --
what they're working on, how they'd like you to communicate, anything
that would obviously save them from repeating themselves later. Keep it
to 2-4 short questions, not an interrogation, and only do this once per
account (once `search_memory` starts returning real results, the account
isn't empty anymore -- stop asking and just recall normally).

## Store last

When something durable and reusable comes up -- a preference, a project
fact, a decision, a correction to something you got wrong -- call
`add_memory` with it. The bar: would this still be true, and still worth
knowing, in a different conversation next week? If yes, save it. If it's
only relevant to finishing the current task (a stack trace, a file path
you're mid-edit on, a transient debugging detail), don't -- that's noise
the extraction pipeline would rather not have to sort through later.

Don't ask permission before saving an ordinary fact -- that's what the
tool is for. Do mention briefly what you saved ("noted that you prefer
code reviews phrased as questions"), so the user can correct it if
`add_memory`'s extraction got it wrong, and can use `forget_memory` if
they'd rather you hadn't.

## Corrections aren't new facts

If the user corrects something you previously saved, call `forget_memory`
with a specific enough description to hit the one outdated fact (it only
ever deletes the single best match, on purpose), then `add_memory` the
corrected version. Don't just add the correction on top and leave the old
version sitting there contradicting it.
