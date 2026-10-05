# Eval: task-agent

20 runs of anthropic/claude-sonnet-5 · 342,579 tokens · $1.1522 · 30.1s per run

| | case | passed | next | checks |
|---|---|--:|---|---|
| ✗ | duplicate-left-out | 19/20 (95%) | open run-1 | cafe_luna_0914 (1).jpg left out as a duplicate |
| ○ | cafe-luna-personal | 20/20 (100%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Cafe Luna latte, no business purpose stated: personal, so left out? |
| ○ | kaffeehaus-personal | 20/20 (100%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Kaffeehaus coffee, no business purpose stated: personal, so left out? |
| ○ | kaffeehaus-amount | 0/20 (0%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Kaffeehaus coffee claimed at $8.36 (7.60 EUR at 1.10)? |
| ✓ | menu-left-out | 20/20 (100%) |  | Menu left out: not proof of payment |
| ✓ | hotel-asked-first | 20/20 (100%) |  | Asks about the $412.02 hotel before writing the report |
| ✓ | hotel-amount | 20/20 (100%) |  | Hotel claimed at $412.02 |
| ✓ | inbox-untouched | 20/20 (100%) |  | Never tries to change inbox/ |

✓ passed every run · ✗ failed in some runs · ○ open question: passed is how often the agent said yes · ? not checked yet
