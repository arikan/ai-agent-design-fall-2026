"""One command, `jobagent`, for everything. Run it with `uv run jobagent <command>`.

On your computer
  serve [--port 8765] [--no-open]   the Job Agent page at localhost, with work/db as its database
  run [manual] [--model <id>]       one whole run: collect, rank, score, write to work/db
  suggest [--model <id>]            suggest Profile changes from your verdicts

Parts, to run one step at a time
  judge [--model <id>]              score work/batch.json -> work/judgments.json
  sources test                      every adapter against its saved responses, offline
  sources try <source.json> [out]   one source, live, with a sample
  sources fetch|domains <config>    every enabled source / the domains they need
  engine prepare|finish <config>    collect, filter, rank / check and total the scores
  engine rank-fixture               write tests/rank_fixture.json for tests/rank_test.js
  db config [manual]|export|seed|apply|progress <stage>
                                    move data between work/db and the run's files

In Claude's cloud (RUN.md)
  prepare [manual]                  everything before the model scores
  finish [--model <id>]             everything after
  suggest prepare | suggest finish [--model <id>]
  usage                             this Claude session's token use
"""

import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])

    def call(module, name, args):
        sys.argv = [name] + args
        module.main()

    if cmd == "serve":
        from . import serve
        serve.main(rest)
    elif cmd == "run":
        from . import run
        call(run, "run", ["local"] + rest)
    elif cmd == "suggest" and rest[:1] in (["prepare"], ["finish"]):
        from . import suggest
        call(suggest, "suggest", rest)
    elif cmd == "suggest":
        from . import run
        call(run, "run", ["suggest"] + rest)
    elif cmd in ("prepare", "finish"):
        from . import run
        call(run, "run", [cmd] + rest)
    elif cmd == "judge":
        from . import judge
        judge.main(rest)
    elif cmd == "sources":
        from . import sources
        call(sources, "sources", rest)
    elif cmd == "engine":
        from . import engine
        call(engine, "engine", rest)
    elif cmd == "db":
        from . import dbio
        call(dbio, "db", rest)
    elif cmd == "usage":
        from . import usage
        call(usage, "usage", rest)
    else:
        print(__doc__)
        sys.exit(0 if cmd in ("", "help", "-h", "--help") else 2)


if __name__ == "__main__":
    main()
