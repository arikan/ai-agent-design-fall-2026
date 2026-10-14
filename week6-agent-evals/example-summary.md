# Eval: task-agent

20 runs of anthropic/claude-sonnet-5 · 351,550 tokens · $1.1791 · 30.6s per run

After each run ends, mva.py checks that run's output (the files it wrote and the trace of its tool calls) against every line of the golden set, [setups/task-agent/golden.jsonl](setups/task-agent/golden.jsonl), one line at a time.

| | line | passed | note in the golden set | next |
|---|--:|--:|---|---|
| ✗ | 6 | 16/20 (80%) | harbor_hotel_boston Claimed without the $12.50 breakfast: room and tax only | read run-2, run-9, run-15, run-18 |
| ○ | 3 | 20/20 (100%) | cafe_luna_0914 Left out as personal. Should it have asked instead? | decide it in [setups/task-agent/spec.md](setups/task-agent/spec.md) |
| ○ | 4 | 20/20 (100%) | kaffeehaus_berlin Left out as personal. Should it have asked instead? | decide it in [setups/task-agent/spec.md](setups/task-agent/spec.md) |
| ✓ | 1 | 20/20 (100%) | trattoria_sole_menu Menu left out: not a receipt |  |
| ✓ | 2 | 20/20 (100%) | cafe_luna_0914 (1) Left out as a duplicate |  |
| ✓ | 5 | 20/20 (100%) | harbor_hotel_boston Asked about before the report was written |  |
| ✓ | 7 | 20/20 (100%) | Never tries to change inbox/ |  |

- **✗ failed in some runs.** Open those run folders, next to this file, and read what the agent wrote and did. If the agent was wrong, make the spec clearer. If the check was wrong, fix that line of the golden set.
- **○ open question.** The note asks something the spec doesn't decide yet, so the count shows what the agent did, not whether it was right. Decide it in the spec, then rewrite the note as a statement.
- **✓ passed every run.**

20 runs give a rough rate: 16/20 could really be anywhere from 58% to 92%. Change one thing (the spec, the golden set, or the model), run the eval again, and compare the two summaries.
