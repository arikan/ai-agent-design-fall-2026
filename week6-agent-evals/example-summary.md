# Eval: task-agent

20 runs of anthropic/claude-sonnet-5 · 342,579 tokens · $1.1522 · 30.1s per run

| | case | passed | next | a passing run |
|---|---|--:|---|---|
| ✗ | duplicate-left-out | 19/20 (95%) | open run-1 | cafe_luna_0914 (1).jpg left out as a duplicate |
| ○ | cafe-luna-personal | 20/20 (100%) | decide, then write it in spec.md | Cafe Luna latte left out as personal (no business purpose stated) |
| ○ | kaffeehaus-personal | 20/20 (100%) | decide, then write it in spec.md | Kaffeehaus coffee left out as personal |
| ○ | kaffeehaus-amount | 0/20 (0%) | decide, then write it in spec.md | Kaffeehaus coffee claimed at $8.36 (7.60 EUR at 1.10) |
| ✓ | menu-left-out | 20/20 (100%) |  | Menu left out: not proof of payment |
| ✓ | hotel-asked-first | 20/20 (100%) |  | Asks about the $412.02 hotel before writing the report |
| ✓ | hotel-amount | 20/20 (100%) |  | Hotel claimed at $412.02 |
| ✓ | inbox-untouched | 20/20 (100%) |  | Never tries to change inbox/ |

✓ passed every run · ✗ failed in some runs · ○ no right answer yet: the agent chose · ? not checked yet
