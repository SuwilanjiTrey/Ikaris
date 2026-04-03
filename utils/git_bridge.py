"""
git_bridge.py  —  PyQt ↔ git bridge for Ikaris Dev Studio
──────────────────────────────────────────────────────────
Registers all git operations as @pyqtSlot methods on WebBridge.
The HTML frontend calls these via QWebChannel and receives state
updates back via page().runJavaScript("updateState(...)").

Usage in main.py  (inside WebBridge or as a mixin):

    from git_bridge import GitBridge

    class WebBridge(QObject, GitBridge):
        def __init__(self, editor):
            super().__init__()
            self.mainWindow = editor
from PyQt5.QtWebChannel import QWebChannel

Then in setup_editor_and_image, after creating gitHandler:

    from git_bridge import GitBridge
    GitBridge.setup(self.bridge, self.gitHandler)

Or just inherit GitBridge in WebBridge — see bottom of file.
"""

import os
import json
import subprocess
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSlot
from PyQt5.QtWebChannel import QWebChannel



# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: str | None = None) -> tuple[str, str, int]:
    """Run a git command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=30
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "git not found", 1
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1


def _git(args: list[str], cwd: str | None = None) -> tuple[str, str, int]:
    return _run(["git"] + args, cwd=cwd)


def _is_repo(path: str) -> bool:
    _, _, rc = _git(["rev-parse", "--is-inside-work-tree"], path)
    return rc == 0


def _repo_root(path: str) -> str | None:
    out, _, rc = _git(["rev-parse", "--show-toplevel"], path)
    return out if rc == 0 else None


# ── state builder ─────────────────────────────────────────────────────────────

def build_state(cwd: str | None) -> dict:
    """
    Run a batch of git queries and return a JSON-serialisable dict
    that matches what the HTML frontend expects in updateState().
    """
    if not cwd or not os.path.isdir(cwd):
        return {"repo": "", "branch": "—", "message": "No folder open"}

    if not _is_repo(cwd):
        return {"repo": os.path.basename(cwd), "branch": "—",
                "message": "Not a git repository"}

    root = _repo_root(cwd) or cwd
    repo_name = os.path.basename(root)

    # Current branch
    branch_out, _, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    branch = branch_out or "HEAD"

    # Local branches
    lb_out, _, _ = _git(["branch", "--format=%(refname:short)"], root)
    local_branches = [b for b in lb_out.splitlines() if b]

    # Remote branches
    rb_out, _, _ = _git(["branch", "-r", "--format=%(refname:short)"], root)
    remote_branches = [b for b in rb_out.splitlines() if b and "HEAD" not in b]

    # Ahead / behind
    ahead = behind = 0
    ab_out, _, rc = _git(
        ["rev-list", "--count", "--left-right", f"@{{u}}...HEAD"], root)
    if rc == 0 and "\t" in ab_out:
        parts = ab_out.split("\t")
        try:
            behind = int(parts[0])
            ahead  = int(parts[1])
        except ValueError:
            pass

    # Status (porcelain v1)
    st_out, _, _ = _git(["status", "--porcelain"], root)
    unstaged = []
    staged   = []
    for line in st_out.splitlines():
        if len(line) < 4:
            continue
        index_s = line[0]   # staged status
        work_s  = line[1]   # working-tree status
        path    = line[3:]

        if index_s != " " and index_s != "?":
            staged.append({"path": path, "status": index_s})
        if work_s not in (" ", ""):
            status = "?" if work_s == "?" else work_s
            unstaged.append({"path": path, "status": status})

    # Commit log (last 50)
    log_fmt  = "%H\x1f%s\x1f%an\x1f%ar\x1f%D"
    log_out, _, _ = _git(
        ["log", "--max-count=50", f"--pretty=format:{log_fmt}"], root)
    log_entries = []
    for entry in log_out.splitlines():
        parts = entry.split("\x1f")
        if len(parts) < 5:
            continue
        refs = [r.strip() for r in parts[4].split(",") if r.strip()
                and "HEAD ->" not in r]
        log_entries.append({
            "hash":   parts[0],
            "msg":    parts[1],
            "author": parts[2],
            "date":   parts[3],
            "refs":   refs,
        })

    # Remotes
    rem_out, _, _ = _git(["remote", "-v"], root)
    seen = set()
    remotes = []
    for line in rem_out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in seen and "(fetch)" in line:
            seen.add(parts[0])
            remotes.append({"name": parts[0], "url": parts[1]})

    # Stash
    stash_out, _, _ = _git(
        ["stash", "list", "--pretty=format:%gd %s"], root)
    stash = [{"message": l} for l in stash_out.splitlines() if l]

    return {
        "repo":           repo_name,
        "branch":         branch,
        "branches":       local_branches,
        "remoteBranches": remote_branches,
        "unstaged":       unstaged,
        "staged":         staged,
        "stash":          stash,
        "log":            log_entries,
        "remotes":        remotes,
        "ahead":          ahead,
        "behind":         behind,
        "message":        "Ready",
        "_root":          root,   # internal, not used by frontend
    }


# ── Bridge class ──────────────────────────────────────────────────────────────

class GitBridge:
    """
    All git-related pyqtSlots.

    Inherit alongside QObject in WebBridge, or instantiate separately and
    register as its own QWebChannel object ("GitBridge").

    Requires:
        self.mainWindow  — CodeEditor instance  (for base_directory)
        self._git_view   — QWebEngineView showing git.html
    Call setup(view) once after the view is created.
    """

    def setup_git(self, git_view):
        """Store the view reference and do first paint."""
        self._git_view = git_view
        self._git_view.loadFinished.connect(lambda: self._push_state())


    # ── internal helpers ──────────────────────────────────────────────────────

    def _cwd(self) -> str | None:
        return getattr(self.mainWindow, "base_directory", None)

    def _root(self) -> str | None:
        cwd = self._cwd()
        if not cwd:
            return None
        return _repo_root(cwd)

    def _push_state(self, extra_msg: str = ""):
        state = build_state(self._cwd())
        if extra_msg:
            state["message"] = extra_msg
        js = f"updateState({json.dumps(state)})"
        if hasattr(self, "_git_view") and self._git_view:
            self._git_view.page().runJavaScript(js)

    def _push_diff(self, diff: str):
        safe = json.dumps(diff)
        if hasattr(self, "_git_view") and self._git_view:
            self._git_view.page().runJavaScript(f"updateDiff({safe})")

    def _run(self, args, msg_ok="", msg_err="") -> bool:
        root = self._root()
        out, err, rc = _git(args, root)
        if rc == 0:
            self._push_state(msg_ok or out[:80])
        else:
            self._push_state(f"Error: {err[:120]}")
        return rc == 0

    # ── slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def git_refresh(self):
        self._push_state("Refreshed")

    @pyqtSlot()
    def git_fetch(self):
        self._run(["fetch", "--all", "--prune"], "Fetch complete")

    @pyqtSlot(str)
    def git_fetch_remote(self, remote: str):
        self._run(["fetch", remote, "--prune"], f"Fetched {remote}")

    @pyqtSlot()
    def git_pull(self):
        self._run(["pull"], "Pull complete")

    @pyqtSlot(str)
    def git_pull_remote(self, remote: str):
        self._run(["pull", remote], f"Pulled from {remote}")

    @pyqtSlot()
    def git_push(self):
        root   = self._root()
        branch_out, _, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        branch = branch_out or "HEAD"
        self._run(["push", "-u", "origin", branch], "Push complete")

    @pyqtSlot(str)
    def git_push_remote(self, remote: str):
        root   = self._root()
        branch_out, _, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        branch = branch_out or "HEAD"
        self._run(["push", remote, branch], f"Pushed to {remote}")

    @pyqtSlot(str)
    def git_stage(self, path: str):
        self._run(["add", path], f"Staged {os.path.basename(path)}")

    @pyqtSlot()
    def git_stage_all(self):
        self._run(["add", "-A"], "All changes staged")

    @pyqtSlot(str)
    def git_unstage(self, path: str):
        self._run(["restore", "--staged", path],
                  f"Unstaged {os.path.basename(path)}")

    @pyqtSlot()
    def git_unstage_all(self):
        self._run(["restore", "--staged", "."], "All changes unstaged")

    @pyqtSlot(str)
    def git_commit(self, message: str):
        self._run(["commit", "-m", message], f"Committed: {message[:60]}")

    @pyqtSlot(str)
    def git_commit_and_push(self, message: str):
        root = self._root()
        _git(["commit", "-m", message], root)
        branch_out, _, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        branch = branch_out or "HEAD"
        self._run(["push", "-u", "origin", branch], "Committed & pushed")

    @pyqtSlot(str)
    def git_amend(self, message: str):
        args = ["commit", "--amend", "--no-edit"] if not message \
               else ["commit", "--amend", "-m", message]
        self._run(args, "Last commit amended")

    @pyqtSlot(str)
    def git_checkout(self, branch: str):
        self._run(["checkout", branch], f"Checked out {branch}")

    @pyqtSlot(str)
    def git_checkout_remote(self, remote_branch: str):
        # e.g. "origin/feature" → local branch "feature"
        local = remote_branch.split("/", 1)[-1]
        self._run(["checkout", "-b", local, "--track", remote_branch],
                  f"Tracking {remote_branch} as {local}")

    @pyqtSlot(str, str)
    def git_create_branch(self, name: str, from_ref: str):
        self._run(["checkout", "-b", name, from_ref or "HEAD"],
                  f"Branch '{name}' created & checked out")

    @pyqtSlot(str)
    def git_delete_branch(self, branch: str):
        self._run(["branch", "-d", branch], f"Branch '{branch}' deleted")

    @pyqtSlot(str)
    def git_merge(self, branch: str):
        self._run(["merge", branch], f"Merged {branch}")

    @pyqtSlot()
    def git_stash(self):
        self._run(["stash"], "Changes stashed")

    @pyqtSlot(int)
    def git_stash_pop(self, index: int):
        self._run(["stash", "pop", f"stash@{{{index}}}"],
                  f"Stash #{index} applied")

    @pyqtSlot(int)
    def git_stash_drop(self, index: int):
        self._run(["stash", "drop", f"stash@{{{index}}}"],
                  f"Stash #{index} dropped")

    @pyqtSlot()
    def git_reset_head(self):
        self._run(["reset", "HEAD"], "HEAD reset (files kept)")

    @pyqtSlot(str, str)
    def git_clone(self, url: str, dest: str):
        cwd = dest if dest and os.path.isdir(dest) else (self._cwd() or str(Path.home()))
        out, err, rc = _run(["git", "clone", url], cwd)
        msg = "Clone complete" if rc == 0 else f"Clone failed: {err[:100]}"
        self._push_state(msg)

    @pyqtSlot(str, str)
    def git_add_remote(self, name: str, url: str):
        self._run(["remote", "add", name, url], f"Remote '{name}' added")

    @pyqtSlot(str)
    def git_remove_remote(self, name: str):
        self._run(["remote", "remove", name], f"Remote '{name}' removed")

    @pyqtSlot(str)
    def git_diff_file(self, path: str):
        root = self._root()
        out, _, _ = _git(["diff", "HEAD", "--", path], root)
        if not out:
            out, _, _ = _git(["diff", "--cached", "--", path], root)
        self._push_diff(out or "# No diff available")

    @pyqtSlot(str)
    def git_diff_commit(self, commit_hash: str):
        root = self._root()
        out, _, _ = _git(["show", "--stat", "-p", commit_hash], root)
        self._push_diff(out or "# No diff available")


# ── Integration snippet ───────────────────────────────────────────────────────
"""
HOW TO WIRE INTO main.py
─────────────────────────

1. Import at top:
    from git_bridge import GitBridge

2. Make WebBridge inherit from it:
    class WebBridge(QObject, GitBridge):
        def __init__(self, editor):
            QObject.__init__(self)
            self.mainWindow = editor

3. In setup_editor_and_image, after creating self.gitHandler:
    self.bridge.setup_git(self.gitHandler)

4. Register GitBridge slots on the channel:
    self.channel.registerObject("WebBridge", self.bridge)
    # (GitBridge slots are already on bridge since it's a base class)

5. Replace the old git_commit / git_push / git_pull stubs on WebBridge
   (delete them — GitBridge now handles all of these).

6. In github() toggle method — call git_refresh when showing:
    if self.github_visible:
        self.bridge.git_refresh()   # paint latest state
        ...show gitHandler...

7. Optional auto-refresh when directory changes (in update_directory):
    self.bridge.git_refresh()
"""
