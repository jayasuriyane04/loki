# LOKI — Real-user testing protocol

The offline evaluations use synthetic speech and a fictional project. This protocol covers what they can't: your
own voice and room, your real projects, and whether LOKI is actually useful day to day.

## Setup (once)

1. Start LOKI (from source, or `docker compose --profile app up -d`; see the README).
2. Use headphones for the first voice session. Without them LOKI can hear itself and interrupt its own reply.
3. Ratings: every reply has 👍 / 👎. Rate replies as you go; the counts appear on the Analytics page.

## One week of normal use

Use LOKI for real work and log anything surprising in a note (ask LOKI: "save a note titled 'LOKI test log' …").
At the end of the week, look at the Analytics page for 7 days:

| Question | Where to look | Healthy |
|---|---|---|
| Is it fast enough? | Time to first word p50 / p95 | < 1.5 s / < 4 s |
| Does voice feel natural? | Time to first audio p50 | < 2 s |
| Does it hear me? | Recognition errors, "no speech" count, your note of misheard words | < 5% of voice turns |
| Do tools work? | Tool success rate, failure recovery | > 95% (declined by you doesn't count) |
| Does it make things up? | Invented citations, safety-net corrections | rare; read the traces when they happen |
| Is it useful? | 👍 vs 👎 | mostly 👍 |

## Scripted checks (about 20 minutes)

Do each one, then mark ✅ or ❌ with a note.

**Voice**
- [ ] Ask three questions by voice at a normal distance from the microphone, with background noise (music or a fan).
- [ ] Interrupt a long answer by speaking. LOKI should stop within a moment and answer the new question.
- [ ] Say "stop" during an answer. It should go quiet and not save anything.
- [ ] Ask something with a name or a technical term you use ("Postgres", "Tarka"). Check the transcript.

**Memory and projects**
- [ ] Tell LOKI a preference ("I prefer short answers") and check it in Memory. Next day: does it still apply?
- [ ] Work on a real project for a few turns. The next day, ask "what did we discuss yesterday?"
- [ ] Say "let's continue <project>". The project chip should appear, and the answer should use what it knows.

**Knowledge base**
- [ ] Upload or watch a real project folder. Ask three questions you know the answers to. Are the citations right?
- [ ] Ask something the files don't cover. LOKI should say so rather than guess.

**Actions**
- [ ] "Remind me in 10 minutes to …": the notification arrives on time.
- [ ] "Add a task … due Friday 5pm". Check the date in the Planner.
- [ ] Ask LOKI to delete something and decline the approval. Nothing should be deleted, and it should say so.

**Proactive (if enabled)**
- [ ] Daily briefing arrives at the set time; quiet hours hold alerts until they end.

## After testing

- 👎 replies: open the conversation, find the turn on the Analytics page (Recent traces), and note what went wrong:
  retrieval (no passages), the model, or a tool.
- Anything misheard, wrong or slow is a candidate for a new eval case: add it to
  `backend/eval/datasets/rag/queries.jsonl` or `agent_scenarios.py` so it stays fixed.
