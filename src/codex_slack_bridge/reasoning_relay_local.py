from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

TEXT_SUFFIXES = frozenset({
    ".py", ".ps1", ".bat", ".cmd", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".md", ".txt", ".csv", ".tsv", ".sql", ".html", ".css", ".xml",
    ".sh", ".dockerfile", ".gitignore", ".gitattributes",
})
IGNORED_DIRS = frozenset({".git", ".venv", "venv", "node_modules", ".packages", "__pycache__", ".pytest_cache"})
SECRET_FILE_RE = re.compile(
    r"(?i)(?:^|[._-])(?:secret|secrets|credential|credentials|token|tokens|private[_-]?key|service[_-]?account|vault)(?:[._-]|$)"
)
SECRET_EXACT = frozenset({".env", "id_rsa", "id_ed25519", "credentials.json", "token.json", "vault.json"})
DENIED_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})


@dataclass(frozen=True)
class LocalRoot:
    name: str
    path: Path
    writable: bool


class LocalWorkspaceBroker:
    """Bounded local file/test tools that replace Codex's implicit filesystem access."""

    def __init__(self, *, lane: str, agent: Mapping[str, Any], child_env: Mapping[str, str]) -> None:
        self.lane = str(lane or "").strip()
        workspace = Path(os.path.expandvars(os.path.expanduser(str(agent.get("workspace_root") or ".")))).expanduser().resolve()
        sandbox_root = Path(os.path.expandvars(os.path.expanduser(str(agent.get("agent_sandbox_root") or "data/agent_sandboxes")))).expanduser()
        if not sandbox_root.is_absolute():
            sandbox_root = (Path.cwd() / sandbox_root).resolve()
        sandbox = (sandbox_root / self.lane).resolve()
        sandbox.mkdir(parents=True, exist_ok=True)
        if not workspace.is_dir():
            raise FileNotFoundError(f"workspace root does not exist for {self.lane}")
        workspace_writable = self.lane in {"direct_codex", "coding_agent"}
        roots = {
            "workspace": LocalRoot("workspace", workspace, workspace_writable),
            "sandbox": LocalRoot("sandbox", sandbox, True),
        }
        attachments_raw = os.path.expandvars(os.path.expanduser(str(agent.get("agent_chat_attachment_dir") or ""))).strip()
        if attachments_raw:
            attachments = Path(attachments_raw).expanduser()
            if not attachments.is_absolute():
                attachments = (Path.cwd() / attachments).resolve()
            if attachments.is_dir():
                roots["attachments"] = LocalRoot("attachments", attachments, False)
        self.roots = roots
        self.child_env = dict(child_env)

    @property
    def available(self) -> bool:
        return True

    def list_tools(self) -> dict[str, Any]:
        tools = [
            _tool("list_dir", True, "List one bounded directory under workspace, sandbox, or attachments."),
            _tool("read_text", True, "Read a bounded UTF-8/text file. Secret-bearing paths are blocked."),
            _tool("search_text", True, "Search bounded text files under one local root."),
            _tool("git_status", True, "Read git status for the configured workspace repository."),
            _tool("git_diff", True, "Read a bounded git diff for the configured workspace repository."),
            _tool("python_compile", True, "Syntax-compile selected Python files without importing them."),
        ]
        if any(root.writable for root in self.roots.values()):
            tools.extend(
                [
                    _tool("write_text", False, "Write one bounded text file inside an allowed writable root."),
                    _tool("delete_file", False, "Delete one exact regular file inside an allowed writable root."),
                ]
            )
        if self.lane in {"direct_codex", "coding_agent"}:
            tools.append(_tool("run_pytest", False, "Run focused pytest paths under the configured workspace."))
        return {"ok": True, "server": "local_workspace", "tools": tools, "count": len(tools)}

    def execute(self, tool: str, arguments: Mapping[str, Any], *, allow_write: bool) -> dict[str, Any]:
        name = str(tool or "").strip()
        args = dict(arguments)
        if name == "list_dir":
            return self._list_dir(args)
        if name == "read_text":
            return self._read_text(args)
        if name == "search_text":
            return self._search_text(args)
        if name == "git_status":
            return self._git_status()
        if name == "git_diff":
            return self._git_diff(args)
        if name == "python_compile":
            return self._python_compile(args)
        if name in {"write_text", "delete_file", "run_pytest"} and not allow_write:
            raise PermissionError("the trusted request did not authorize this local mutation/execution")
        if name == "write_text":
            return self._write_text(args)
        if name == "delete_file":
            return self._delete_file(args)
        if name == "run_pytest":
            return self._run_pytest(args)
        raise ValueError("local workspace tool is not exposed")

    def _root(self, name: Any) -> LocalRoot:
        key = str(name or "workspace").strip().lower()
        root = self.roots.get(key)
        if root is None:
            raise ValueError("local root is unavailable")
        return root

    def _path(self, root: LocalRoot, value: Any, *, must_exist: bool = False) -> Path:
        raw = str(value or "").replace("\\", "/").strip().lstrip("/")
        if len(raw) > 500 or any(part in {"", ".", ".."} for part in raw.split("/")):
            raise ValueError("local relative path is invalid")
        target = (root.path / raw).resolve()
        try:
            target.relative_to(root.path)
        except ValueError as exc:
            raise PermissionError("local path escaped its configured root") from exc
        self._reject_sensitive(target, root)
        if must_exist and not target.exists():
            raise FileNotFoundError("local path does not exist")
        return target

    @staticmethod
    def _reject_sensitive(path: Path, root: LocalRoot) -> None:
        relative = path.relative_to(root.path)
        for part in relative.parts:
            low = part.casefold()
            if low in SECRET_EXACT or Path(low).suffix in DENIED_SUFFIXES or SECRET_FILE_RE.search(low):
                raise PermissionError("secret-bearing local paths are not available to the reasoning relay")
        lowered = "/".join(part.casefold() for part in relative.parts)
        if any(segment in lowered for segment in ("data/auth/", "secure-vault/", "/.ssh/")):
            raise PermissionError("private authentication state is not available to the reasoning relay")

    def _list_dir(self, args: Mapping[str, Any]) -> dict[str, Any]:
        root = self._root(args.get("root"))
        relative = str(args.get("path") or "").strip()
        target = root.path if not relative else self._path(root, relative, must_exist=True)
        if not target.is_dir():
            raise ValueError("list_dir target is not a directory")
        limit = max(1, min(int(args.get("limit") or 200), 500))
        rows = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
            try:
                self._reject_sensitive(child.resolve(), root)
            except PermissionError:
                continue
            rows.append({
                "name": child.name,
                "path": child.resolve().relative_to(root.path).as_posix(),
                "type": "directory" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else None,
            })
            if len(rows) >= limit:
                break
        return {"ok": True, "root": root.name, "path": relative, "entries": rows}

    def _read_text(self, args: Mapping[str, Any]) -> dict[str, Any]:
        root = self._root(args.get("root"))
        target = self._path(root, args.get("path"), must_exist=True)
        if not target.is_file():
            raise ValueError("read_text target is not a file")
        max_bytes = max(1000, min(int(args.get("max_bytes") or 200_000), 500_000))
        raw = target.read_bytes()[: max_bytes + 1]
        truncated = len(raw) > max_bytes
        if truncated:
            raw = raw[:max_bytes]
        text = raw.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "root": root.name,
            "path": target.relative_to(root.path).as_posix(),
            "text": text,
            "truncated": truncated,
        }

    def _search_text(self, args: Mapping[str, Any]) -> dict[str, Any]:
        root = self._root(args.get("root"))
        query = str(args.get("query") or "")
        if not query or len(query) > 500:
            raise ValueError("search query is required and must be at most 500 characters")
        base_raw = str(args.get("path") or "").strip()
        base = root.path if not base_raw else self._path(root, base_raw, must_exist=True)
        if not base.is_dir():
            raise ValueError("search_text path must be a directory")
        glob = str(args.get("glob") or "*").strip() or "*"
        limit = max(1, min(int(args.get("limit") or 100), 300))
        matches: list[dict[str, Any]] = []
        scanned = 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
            for filename in filenames:
                if not fnmatch.fnmatch(filename, glob):
                    continue
                path = Path(dirpath) / filename
                try:
                    self._reject_sensitive(path.resolve(), root)
                except PermissionError:
                    continue
                if path.suffix.casefold() not in TEXT_SUFFIXES and "." in filename:
                    continue
                scanned += 1
                if scanned > 2000:
                    return {"ok": True, "matches": matches, "truncated": True, "scannedFiles": scanned}
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for number, line in enumerate(text.splitlines(), start=1):
                    if query.casefold() in line.casefold():
                        matches.append({
                            "path": path.resolve().relative_to(root.path).as_posix(),
                            "line": number,
                            "text": line[:1000],
                        })
                        if len(matches) >= limit:
                            return {"ok": True, "matches": matches, "truncated": True, "scannedFiles": scanned}
        return {"ok": True, "matches": matches, "truncated": False, "scannedFiles": scanned}

    def _write_text(self, args: Mapping[str, Any]) -> dict[str, Any]:
        root = self._root(args.get("root"))
        if not root.writable:
            raise PermissionError("this lane cannot write to the selected local root")
        target = self._path(root, args.get("path"), must_exist=False)
        relative = target.relative_to(root.path).as_posix()
        if relative.casefold().startswith(".github/workflows/"):
            raise PermissionError("workflow files require the guarded GitHub release path")
        content = str(args.get("content") or "")
        if len(content.encode("utf-8")) > 500_000:
            raise ValueError("write_text content is too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        readback = target.read_text(encoding="utf-8")
        if readback != content:
            raise RuntimeError("local write readback failed")
        return {"ok": True, "root": root.name, "path": relative, "bytes": len(content.encode("utf-8"))}

    def _delete_file(self, args: Mapping[str, Any]) -> dict[str, Any]:
        root = self._root(args.get("root"))
        if not root.writable:
            raise PermissionError("this lane cannot delete from the selected local root")
        target = self._path(root, args.get("path"), must_exist=True)
        if not target.is_file():
            raise ValueError("delete_file target is not a regular file")
        relative = target.relative_to(root.path).as_posix()
        if relative.casefold().startswith(".github/workflows/"):
            raise PermissionError("workflow files require the guarded GitHub release path")
        target.unlink()
        return {"ok": True, "root": root.name, "path": relative, "deleted": not target.exists()}

    def _git_status(self) -> dict[str, Any]:
        root = self.roots["workspace"].path
        return self._run_readonly(["git", "status", "--short", "--branch"], root, timeout=30)

    def _git_diff(self, args: Mapping[str, Any]) -> dict[str, Any]:
        root = self.roots["workspace"].path
        path = str(args.get("path") or "").replace("\\", "/").strip()
        command = ["git", "diff", "--no-ext-diff", "--"]
        if path:
            self._path(self.roots["workspace"], path, must_exist=False)
            command.append(path)
        return self._run_readonly(command, root, timeout=30)

    def _python_compile(self, args: Mapping[str, Any]) -> dict[str, Any]:
        root = self.roots["workspace"]
        paths = args.get("paths")
        if not isinstance(paths, list) or not paths or len(paths) > 50:
            raise ValueError("python_compile paths must contain 1-50 files")
        clean = []
        for raw in paths:
            path = self._path(root, raw, must_exist=True)
            if not path.is_file() or path.suffix.casefold() != ".py":
                raise ValueError("python_compile accepts Python files only")
            clean.append(str(path))
        command = [os.getenv("PYTHON_EXECUTABLE") or os.sys.executable, "-m", "py_compile", *clean]
        return self._run_readonly(command, root.path, timeout=60)

    def _run_pytest(self, args: Mapping[str, Any]) -> dict[str, Any]:
        if self.lane not in {"direct_codex", "coding_agent"}:
            raise PermissionError("pytest execution is not available to this lane")
        root = self.roots["workspace"]
        paths = args.get("paths")
        if not isinstance(paths, list) or not paths or len(paths) > 20:
            raise ValueError("run_pytest paths must contain 1-20 bounded paths")
        clean = []
        for raw in paths:
            target = self._path(root, raw, must_exist=True)
            clean.append(str(target.relative_to(root.path)))
        timeout = max(10, min(int(args.get("timeout_seconds") or 120), 300))
        env = dict(self.child_env)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        completed = subprocess.run(
            [os.getenv("PYTHON_EXECUTABLE") or os.sys.executable, "-m", "pytest", "-q", *clean],
            cwd=str(root.path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-40_000:],
            "stderr": completed.stderr[-20_000:],
        }

    def _run_readonly(self, command: list[str], cwd: Path, *, timeout: int) -> dict[str, Any]:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=self.child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-40_000:],
            "stderr": completed.stderr[-20_000:],
        }


def _tool(name: str, read_only: bool, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": not read_only,
            "idempotentHint": read_only,
        },
    }
