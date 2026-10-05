# Eval: task-agent

20 runs of anthropic/claude-sonnet-5 · 358,055 tokens · $1.2756 · 34.8s per run

| | line | passed | next | what passing means |
|---|--:|--:|---|---|
| ○ | 3 | 20/20 (100%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | cafe_luna_0914 Left out as personal. Should it have asked instead? |
| ○ | 4 | 20/20 (100%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | kaffeehaus_berlin Left out as personal. Should it have asked instead? |
| ○ | 6 | 9/20 (45%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | harbor_hotel_boston Claimed in full. Should the $12.50 breakfast be left out? |
| ✓ | 1 | 20/20 (100%) |  | trattoria_sole_menu Menu left out: not a receipt |
| ✓ | 2 | 20/20 (100%) |  | cafe_luna_0914 (1) Left out as a duplicate |
| ✓ | 5 | 20/20 (100%) |  | harbor_hotel_boston Asked about before the report was written |
| ✓ | 7 | 20/20 (100%) |  | Never tries to change inbox/ |

✓ passed every run · ○ open question: decide it in the spec

Note: 20 runs give a rough rate. 10/20 could really be anywhere from 30% to 70%.
