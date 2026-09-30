# Terminal, VS Code and Git

The labs use three everyday tools. This page covers what you need of each, with links to learn more.

## Terminal

You run the labs by typing commands in a terminal: Terminal on macOS, the terminal panel in VS Code, or PowerShell on Windows. A terminal is always inside one folder, the **working directory**, and every path you type starts from there. Most of the time you'll be moving between folders and looking at what's in them.

| Command | What it does | Example in the course repo |
|---|---|---|
| `pwd` | Shows the folder you're in | `pwd` ends in `ai-agent-design-fall-2026` |
| `ls` | Lists what's in a folder | `ls week5-minimal-agent` |
| `ls -a` | Also lists hidden files, whose names start with `.` | `ls -a` shows `.gitignore` |
| `cd <folder>` | Moves into a folder | `cd week5-minimal-agent` |
| `cd ..` | Moves up one folder | from `week5-minimal-agent` back to the repo |
| `cd ~` | Moves to your home folder | |
| `cat <file>` | Prints a file in the terminal | `cat README.md` |
| `open <file or folder>` | Opens it in its app, or a folder in Finder | `open README.md`, `open .` |
| `cp <from> <to>` | Copies a file; `cp -r` copies a folder | `cp .env.example .env` |
| `clear` | Clears the screen | |

A few keys save most of the typing:

- **Tab** completes a file or folder name. Press it twice to see the choices.
- **Up arrow** brings back your earlier commands, so you can rerun one with Enter.
- **Ctrl-C** stops the command that is running.

In a path, `..` means the folder above, `.` the folder you're in, and `~` your home folder. A name with spaces needs quotes: `ls "week5-minimal-agent/receipts/cafe_luna_0914 (1).jpg"`.

Each week's commands expect you to be in that week's folder. If a command says it can't find a file, such as `python3` saying it can't open `mva.py`, run `pwd` to see where you are, then `cd` into the week's folder.

On Windows, PowerShell accepts `pwd`, `ls`, `cd`, `cat`, `cp` and `clear` too; use `ls -Force` for hidden files, `cp -Recurse` for folders, and `start <file>` or `explorer .` in place of `open`. On Linux, use `xdg-open` in place of `open`.

To go further, [The Missing Semester: The Shell](https://missing.csail.mit.edu/2020/course-shell/) is a one-hour lecture with notes and exercises.

## VS Code

[VS Code](https://code.visualstudio.com) is a free code editor from Microsoft: you open a folder in it, and you can browse, read and edit its files. It also has a built-in terminal, so the files and the terminal sit in one window, which is the easiest way to work through the labs.

- **Open the folder.** File → Open Folder… and choose the week's folder, such as `week5-minimal-agent`. The sidebar (the Explorer) shows every file in it.
- **Read files.** Click a file in the Explorer to open it: a spec, a CSV, a trace, or an image. For a Markdown file such as a `README.md` or `report.md`, press Cmd-Shift-V (Ctrl-Shift-V on Windows) to see it formatted. Hidden files, whose names start with `.`, show up in the Explorer too.
- **Edit and save files.** Change a file in the editor and save with Cmd-S (Ctrl-S).
- **Use the terminal.** As an alternative to a separate terminal app, open one inside VS Code: Terminal → New Terminal, or Ctrl-\`. It starts in the folder you opened, so the week's commands work right away.

For a longer tour, see [Getting started with VS Code](https://code.visualstudio.com/docs/getstarted/getting-started).

## Git

Git is a version control tool: it tracks every change to the files in a folder, called a **repository** (repo). The course repo lives on GitHub, and git copies it to your computer and brings in each week's new folder. You only need three commands. Run `git pull` and `git status` from any folder inside the repo:

| Command | What it does |
|---|---|
| `git clone <url>` | Copies the repo to your computer, once. The [course README](README.md#getting-the-labs) has the URL. |
| `git pull` | Brings in the latest changes, such as next week's folder. |
| `git status` | Lists the files you've changed or added since the last pull. |

What your runs make, and your `.env`, is ignored by git, so it stays on your machine and never gets in the way of a pull. The files that came with the repo are different: if you edit one, `git pull` may stop. Copy the file or folder and edit the copy instead. To undo your edits to a repo file, run `git restore <file>`.

On macOS, the first `git` command may ask to install the command line developer tools. Say yes. To learn more, see [The Missing Semester: Version Control (Git)](https://missing.csail.mit.edu/2020/version-control/).
