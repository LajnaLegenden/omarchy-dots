# shell functions — utilities shared across bash/zsh/fish

ask() {
  local input
  if [ $# -gt 0 ]; then
    input="$*"
  else
    input=$(cat)
  fi

  MAX_THINKING_TOKENS=0 claude --print --model haiku \
    --system-prompt "You are a terminal quick-answer tool. Rules: plain text only, no markdown, no code fences, no bullet points, no headers, no bold, no trailing follow-up question, max 10 lines. If the question asks how to do something in the shell, reply with ONLY the command(s). Otherwise answer directly in 1-3 short sentences. Use filesystem tools (ls, find, cat, grep, etc.) freely whenever they'd help answer accurately — they're cheap. Web search is expensive: only reach for it when the answer truly requires current/external info you don't already know, and stop after one search. If you're not confident after that, just say you don't know and suggest using a more powerful agent — don't keep digging.

Example 1
User: how do I list files sorted by size
Assistant: ls -lhS

Example 2
User: scp a folder matching a pattern from a server
Assistant: scp -r user@host:/remote/path/folder_* /local/path/

Example 3
User: what does exit code 137 mean
Assistant: Exit code 137 means the process was killed by SIGKILL, usually the OOM killer from running out of memory.

Example 4
User: what's the latest LTS version of node released this week
Assistant: Not sure without deeper research — ask a more powerful agent for up-to-the-minute release info." \
    --allowedTools "Read,Grep,Glob,WebSearch,WebFetch,Bash(ls:*),Bash(find:*),Bash(cat:*),Bash(grep:*),Bash(head:*),Bash(tail:*),Bash(wc:*),Bash(du:*),Bash(df:*),Bash(file:*),Bash(stat:*),Bash(pwd:*),Bash(tree:*),Bash(echo:*),Bash(which:*),Bash(uname:*),Bash(date:*)" \
    -- "$input"
}

# Hard-reset this worktree to origin's default branch (main/master auto-detected)
# or a branch you name. Anything at risk — uncommitted changes and commits not
# already on origin/<branch> — is committed and parked on a wip/ branch first,
# so a bad call is recoverable with `git checkout wip/reset-<stamp>`.
# ponytail: stays on the current branch (just moves its tip) instead of checking
# out <branch>, since git refuses a checkout a sibling worktree already holds.
wtreset() {
  git rev-parse --git-dir >/dev/null 2>&1 || { echo "wtreset: not a git repo" >&2; return 1; }
  git fetch origin --prune || return 1

  local default branch snap b
  default=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
  default=${default#origin/}
  if [ -z "$default" ]; then
    for b in main master; do
      git show-ref --verify --quiet "refs/remotes/origin/$b" && default=$b && break
    done
  fi

  branch=$1
  if [ -z "$branch" ]; then
    printf 'Reset to origin/[%s]: ' "$default"
    read -r branch
    branch=${branch:-$default}
  fi
  git show-ref --verify --quiet "refs/remotes/origin/$branch" ||
    { echo "wtreset: no such remote branch: origin/$branch" >&2; return 1; }

  # Snapshot first: commit the dirty tree, then park HEAD on a wip/ branch if it
  # holds anything origin/<branch> doesn't.
  if [ -n "$(git status --porcelain)" ]; then
    git add -A && git commit --no-verify -q -m "WIP snapshot before wtreset [skip ci]" || return 1
  fi
  if [ -n "$(git rev-list --max-count=1 "origin/$branch..HEAD" 2>/dev/null)" ]; then
    snap="wip/reset-$(date +%Y%m%d-%H%M%S)"
    git branch "$snap" || return 1
    echo "wtreset: work saved on $snap"
  fi

  git reset --hard "origin/$branch"
}
