"""Classifier on the local Claude Code CLI (`claude -p`), using your Claude login instead of an API key.

The CLI is an agent with tools, so a prompt-injected email could in theory ask it to read files or
run commands. Each call is locked down:

- `--tools ""` disables every built-in tool;
- `--system-prompt` replaces the agent prompt with the classification prompt only;
- `--strict-mcp-config` loads no MCP servers;
- `--no-session-persistence` keeps the mail text out of the local session history;
- the call runs in a fresh empty temp directory, and the email goes in on stdin, not in argv
  (argv is visible to other users in the process list).
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Callable

from ..models import Classification, Envelope
from .base import OUTPUT_SCHEMA, SYSTEM_PROMPT, ClassificationError, ConfigError, build_user_prompt, parse_output

Runner = Callable[..., subprocess.CompletedProcess]


class ClaudeCliClassifier:
    name = "claude-cli"

    def __init__(
        self,
        executable: str = "claude",
        model: str = "haiku",
        timeout: float = 180.0,
        use_json_schema: bool = True,
        runner: Runner = subprocess.run,
    ) -> None:
        self.executable = executable
        self.model = model
        self.timeout = timeout
        self.use_json_schema = use_json_schema
        self._run = runner

    def command(self) -> list[str]:
        cmd = [
            self.executable, "-p",
            "--model", self.model,
            "--output-format", "json",
            "--system-prompt", SYSTEM_PROMPT,
            "--tools", "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if self.use_json_schema:
            cmd += ["--json-schema", json.dumps(OUTPUT_SCHEMA)]
        return cmd

    def classify(self, envelope: Envelope, body: str) -> Classification:
        with tempfile.TemporaryDirectory(prefix="job-reply-") as workdir:
            try:
                result = self._run(
                    self.command(),
                    input=build_user_prompt(envelope, body),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=workdir,
                )
            except FileNotFoundError as exc:
                raise ConfigError(f"Claude CLI not found at {self.executable!r}; set CLAUDE_CLI") from exc
            except subprocess.TimeoutExpired as exc:
                raise ClassificationError(f"claude -p timed out after {self.timeout:.0f}s") from exc
        if result.returncode != 0:
            raise ClassificationError(f"claude -p exited with {result.returncode}: {(result.stderr or '').strip()[:200]}")
        lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
        if not lines:
            raise ClassificationError("claude -p printed nothing")
        try:
            envelope_json = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise ClassificationError("claude -p did not print JSON") from exc
        if envelope_json.get("is_error"):
            raise ClassificationError(f"claude -p reported an error: {str(envelope_json.get('result', ''))[:200]}")
        # With --json-schema the CLI returns the validated object in `structured_output`;
        # otherwise the answer is text in `result`, often wrapped in a code fence.
        structured = envelope_json.get("structured_output")
        return parse_output(structured if isinstance(structured, dict) else envelope_json.get("result", ""))
