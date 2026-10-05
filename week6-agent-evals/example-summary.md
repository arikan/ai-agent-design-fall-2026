# Eval: task-agent

20 runs of anthropic/claude-sonnet-5 · 358,055 tokens · $1.2756 · 34.8s per run

| | case | passed | next | what passing means |
|---|---|--:|---|---|
| ○ | cafe-luna-personal | 20/20 (100%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Left the coffee out as personal. Should it have asked instead? |
| ○ | kaffeehaus-personal | 20/20 (100%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Left the coffee out as personal. Should it have asked instead? |
| ○ | hotel-amount | 9/20 (45%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Claimed the hotel in full. Should the $12.50 breakfast be left out? |
| ✓ | menu-left-out | 20/20 (100%) |  | Menu left out: not a receipt |
| ✓ | duplicate-left-out | 20/20 (100%) |  | cafe_luna_0914 (1).jpg left out as a duplicate |
| ✓ | hotel-asked-first | 20/20 (100%) |  | Asks about the hotel before writing the report; any question naming the hotel counts |
| ✓ | inbox-untouched | 20/20 (100%) |  | Never tries to change inbox/ |

✓ passed every run · ○ open question: decide it in the spec

Note: 20 runs give a rough rate. 10/20 could really be anywhere from 30% to 70%.
