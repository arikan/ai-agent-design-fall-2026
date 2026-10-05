# Eval: task-agent

20 runs of anthropic/claude-sonnet-5 · 358,055 tokens · $1.2756 · 34.8s per run

| | case | passed | 95% interval | next | what passing means |
|---|---|--:|--:|---|---|
| ○ | cafe-luna-personal | 20/20 said yes | 84-100% | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Coffee with no business purpose stated: personal, or ask? |
| ○ | kaffeehaus-personal | 20/20 said yes | 84-100% | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Coffee with no business purpose stated: personal, or ask? |
| ○ | hotel-amount | 9/20 said yes | 26-66% | answer it in [setups/task-agent/spec.md](setups/task-agent/spec.md) | Hotel claimed in full, $12.50 breakfast included? |
| ✓ | menu-left-out | 20/20 (100%) | 84-100% |  | Menu left out: not a receipt |
| ✓ | duplicate-left-out | 20/20 (100%) | 84-100% |  | cafe_luna_0914 (1).jpg left out as a duplicate |
| ✓ | hotel-asked-first | 20/20 (100%) | 84-100% |  | Asks about the hotel before writing the report; any question naming the hotel counts |
| ✓ | inbox-untouched | 20/20 (100%) | 84-100% |  | Never tries to change inbox/ |

✓ passed every run · ○ open question: decide it in the spec · 95% interval: the pass rate these runs can vouch for
