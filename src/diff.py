"""
diff.py — Prompt diff computation and display.

Prompts are not code, but they share some structural properties with code.
This module computes diffs that are meaningful at the semantic level, not
just the line level — flagging constraint removals, section changes, and
significant length deltas alongside the standard unified diff.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Diff change types
# ---------------------------------------------------------------------------


class ChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    REORDERED = "reordered"
    UNCHANGED = "unchanged"


# ---------------------------------------------------------------------------
# Structural analysis
# ---------------------------------------------------------------------------


def extract_sections(prompt: str) -> dict[str, str]:
    """
    Parse a prompt into named sections based on Markdown headings.

    Returns a dict mapping section title → section body.
    Handles H2 (##) and H3 (###) headings. Prompts without headings
    are returned as a single section under the key '__preamble__'.

    Example:
        ## Instructions
        You are a helpful assistant...

        ## Output Format
        Respond with valid JSON...

    Returns:
        {
            'Instructions': 'You are a helpful assistant...',
            'Output Format': 'Respond with valid JSON...',
        }
    """
    sections: dict[str, str] = {}
    current_section = "__preamble__"
    current_lines: list[str] = []

    for line in prompt.splitlines():
        heading_match = re.match(r"^#{2,3}\s+(.+)$", line)
        if heading_match:
            if current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def extract_constraints(prompt: str) -> list[str]:
    """
    Heuristically identify explicit prohibition or constraint lines.

    Looks for patterns like:
    - Lines beginning with "Do not", "Never", "Always", "Must not"
    - Lines containing "prohibited", "forbidden", "not allowed"
    - Numbered list items that contain negation keywords

    Returns a list of matched lines (stripped).

    TODO: improve with a more robust NLP-based approach for production use.
    """
    constraint_patterns = [
        r"^\s*(Do not|Never|Always|Must not|You must not|You should not|Avoid)\b",
        r"\b(prohibited|forbidden|not allowed|must not|never)\b",
        r"^\s*[-*]\s.*(never|always|must|do not|don.t)\b",
    ]
    combined = re.compile("|".join(constraint_patterns), re.IGNORECASE)
    return [
        line.strip()
        for line in prompt.splitlines()
        if combined.search(line) and line.strip()
    ]


# ---------------------------------------------------------------------------
# Diff result types
# ---------------------------------------------------------------------------


@dataclass
class SectionDiff:
    """Diff of a single named section between two prompt versions."""

    name: str
    change_type: ChangeType
    before: str = ""
    after: str = ""
    unified_diff: list[str] = field(default_factory=list)

    def has_changes(self) -> bool:
        return self.change_type != ChangeType.UNCHANGED

    def render(self, width: int = 80) -> str:
        """Render section diff as a human-readable block."""
        lines = [f"[{self.change_type.value.upper()}] ## {self.name}"]
        if self.change_type == ChangeType.ADDED:
            for line in self.after.splitlines()[:10]:
                lines.append(f"  + {line}")
            remaining = len(self.after.splitlines()) - 10
            if remaining > 0:
                lines.append(f"  ... (+{remaining} more lines)")
        elif self.change_type == ChangeType.REMOVED:
            for line in self.before.splitlines()[:5]:
                lines.append(f"  - {line}")
        elif self.change_type == ChangeType.MODIFIED:
            lines.extend(f"  {l}" for l in self.unified_diff[:20])
        return "\n".join(lines)


@dataclass
class ConstraintDiff:
    """Summary of constraint changes between two prompt versions."""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.removed

    @property
    def has_removals(self) -> bool:
        return bool(self.removed)

    def render(self) -> str:
        lines: list[str] = []
        if self.removed:
            lines.append("  [CONSTRAINT REMOVALS — reviewer must acknowledge]")
            for c in self.removed:
                lines.append(f"    - {c}")
        if self.added:
            lines.append("  [CONSTRAINT ADDITIONS]")
            for c in self.added:
                lines.append(f"    + {c}")
        return "\n".join(lines) if lines else "  (no constraint changes)"


@dataclass
class PromptDiffResult:
    """
    Complete diff result between two versions of a named prompt.

    Aggregates:
    - Line-level unified diff
    - Section-level structural diff
    - Constraint-level semantic diff
    - Length and metadata deltas
    """

    prompt_name: str
    from_version: str
    to_version: str

    before: str
    after: str

    section_diffs: list[SectionDiff] = field(default_factory=list)
    constraint_diff: ConstraintDiff = field(default_factory=ConstraintDiff)

    risk_indicators: list[str] = field(default_factory=list)
    """Automatically-detected risk signals (e.g. constraint removals, major length delta)."""

    @property
    def line_delta(self) -> int:
        return len(self.after.splitlines()) - len(self.before.splitlines())

    @property
    def char_delta(self) -> int:
        return len(self.after) - len(self.before)

    def changed_sections(self) -> list[SectionDiff]:
        return [s for s in self.section_diffs if s.has_changes()]

    def infer_bump_type(self) -> str:
        """
        Suggest a version bump type based on the diff content.

        Heuristics:
        - Constraint removals → MAJOR
        - New sections → MINOR
        - Large length delta (>20%) → MINOR
        - Only whitespace/punctuation changes → PATCH

        Returns 'patch', 'minor', or 'major'.

        TODO: implement heuristics
        """
        raise NotImplementedError

    def render(self, width: int = 80) -> str:
        """
        Render the full diff as a rich terminal-friendly string.

        TODO: use `rich` for color and panel rendering.
        """
        sep = "─" * width
        header = f" {self.prompt_name}: {self.from_version} → {self.to_version} "
        lines = [
            sep,
            header.center(width, "─"),
            sep,
            f"  Lines: {self.line_delta:+d}  |  Chars: {self.char_delta:+d}",
            f"  Sections changed: {len(self.changed_sections())}",
            "",
        ]
        for sd in self.changed_sections():
            lines.append(sd.render())
            lines.append("")

        lines.append("Constraint changes:")
        lines.append(self.constraint_diff.render())
        lines.append("")

        if self.risk_indicators:
            lines.append("Risk indicators:")
            for ri in self.risk_indicators:
                lines.append(f"  ⚠  {ri}")
        else:
            lines.append("Risk indicators: none flagged")

        lines.append(sep)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


class PromptDiff:
    """
    Computes and caches the diff between two prompt versions.
    """

    @staticmethod
    def compute(
        prompt_name: str,
        from_version: str,
        to_version: str,
        before_text: str,
        after_text: str,
    ) -> PromptDiffResult:
        """
        Compute a full PromptDiffResult from two prompt text strings.

        Steps:
        1. Extract sections from both versions
        2. Compute section-level diffs
        3. Extract and diff constraint lines
        4. Compute unified diff
        5. Detect risk indicators
        """
        # Section diff
        before_sections = extract_sections(before_text)
        after_sections = extract_sections(after_text)
        all_section_names = list(
            dict.fromkeys(list(before_sections.keys()) + list(after_sections.keys()))
        )

        section_diffs: list[SectionDiff] = []
        for name in all_section_names:
            before_body = before_sections.get(name, "")
            after_body = after_sections.get(name, "")

            if not before_body:
                change_type = ChangeType.ADDED
            elif not after_body:
                change_type = ChangeType.REMOVED
            elif before_body == after_body:
                change_type = ChangeType.UNCHANGED
            else:
                change_type = ChangeType.MODIFIED

            unified = list(
                difflib.unified_diff(
                    before_body.splitlines(keepends=True),
                    after_body.splitlines(keepends=True),
                    fromfile=f"{name} (before)",
                    tofile=f"{name} (after)",
                    n=2,
                )
            ) if change_type == ChangeType.MODIFIED else []

            section_diffs.append(SectionDiff(
                name=name,
                change_type=change_type,
                before=before_body,
                after=after_body,
                unified_diff=[l.rstrip("\n") for l in unified],
            ))

        # Constraint diff
        before_constraints = set(extract_constraints(before_text))
        after_constraints = set(extract_constraints(after_text))
        constraint_diff = ConstraintDiff(
            added=sorted(after_constraints - before_constraints),
            removed=sorted(before_constraints - after_constraints),
        )

        # Risk indicators
        risk_indicators: list[str] = []
        if constraint_diff.has_removals:
            risk_indicators.append(
                f"{len(constraint_diff.removed)} constraint(s) removed — "
                "reviewer must explicitly acknowledge"
            )
        before_len = len(before_text)
        after_len = len(after_text)
        if before_len > 0:
            pct_change = abs(after_len - before_len) / before_len
            if pct_change > 0.25:
                risk_indicators.append(
                    f"Prompt length changed by {pct_change:.0%} — verify behavioral intent"
                )

        return PromptDiffResult(
            prompt_name=prompt_name,
            from_version=from_version,
            to_version=to_version,
            before=before_text,
            after=after_text,
            section_diffs=section_diffs,
            constraint_diff=constraint_diff,
            risk_indicators=risk_indicators,
        )

    @classmethod
    def from_versions(
        cls,
        prompt_name: str,
        from_version: str,
        to_version: str,
        versions_dir: str = "prompts/versions",
    ) -> PromptDiffResult:
        """
        Load two version files from disk and compute the diff.

        Expects files at:
          {versions_dir}/{prompt_name}-v{from_version}.md
          {versions_dir}/{prompt_name}-v{to_version}.md

        TODO: implement file loading
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def diff_prompts(
    before: str,
    after: str,
    name: str = "prompt",
    from_version: str = "before",
    to_version: str = "after",
) -> str:
    """
    One-liner: compute and render a prompt diff.

    Returns the rendered diff string, ready for printing.
    """
    result = PromptDiff.compute(name, from_version, to_version, before, after)
    return result.render()
