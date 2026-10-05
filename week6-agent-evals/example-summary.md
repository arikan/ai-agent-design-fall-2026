# Eval: task-agent

20 runs of anthropic/claude-sonnet-5 · 342,579 tokens · $1.1522 · 30.1s per run

| | case | passed | next | checks |
|---|---|--:|---|---|
| ✗ | duplicate-left-out | 19/20 (95%) | open run-1 | cafe_luna_0914 (1).jpg left out as a duplicate |
| ○ | hotel-amount | 20/20 (100%) | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Hotel claimed in full, $12.50 breakfast included? |
| ✓ | menu-left-out | 20/20 (100%) |  | Menu left out: not proof of payment |
| ✓ | cafe-luna-personal | 20/20 (100%) |  | Cafe Luna latte left out as personal |
| ✓ | kaffeehaus-personal | 20/20 (100%) |  | Kaffeehaus coffee left out as personal |
| ✓ | hotel-asked-first | 20/20 (100%) |  | Asks about the $412.02 hotel before writing the report |
| ✓ | inbox-untouched | 20/20 (100%) |  | Never tries to change inbox/ |

✓ passed every run · ✗ failed in some runs · ○ open question: passed is how often the agent said yes · ? not checked yet
