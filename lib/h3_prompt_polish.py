# MiniMax H3 Motion Director - polish the wording, keep the structure.
# Copyright (C) 2026 WakaSoft. GPL-3.0. See LICENSE.

"""Rewrite the user's own prompt in place: better wording, same skeleton.

Every other path in the enhancer decides the *shape* of the answer - MiniMax's
official template, a recipe, or the caption block this pack assembles from images.
That is what you want when the prompt is a note to yourself, and exactly what you
do not want when the prompt is already written in the guide's form: the tags are
bindings (`<Subject 1>` is the identity slot, `<Video 1>` the source window), the
headers are read by whoever opens the file later, and a "helpful" rewrite that
renames a slot, drops a role line or folds two sections into one paragraph costs a
render.

So this mode is deliberately small. The user's prompt goes in verbatim, the answer
must come back with the same headers, the same tags and the same claims, and only
the wording may change. The check is mechanical rather than trusting: `verify`
compares the tag, header and marker inventory of both texts, and a mismatch earns
one retry that names what moved before the result is handed back with a note.

Nothing here imports torch, ComfyUI or an HTTP client: the prompt texts are plain
strings, so the whole contract is unit-testable without a model.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# The mode name the panel sends. The others are accepted so a request written by
# hand (or by an older/newer panel) cannot silently fall into the rewrite path,
# which would reshape a prompt the user asked to keep.
POLISH_MODE = "polish"
POLISH_ALIASES = frozenset(
    {"polish", "polish_only", "polish-only", "wording", "wording_only", "wording-only"}
)

# Tags: any single angle-bracket token. Deliberately generic - `<Subject 1>`,
# `<Picture 2>`, `<Video 1>`, `<Audio 1>` and `<d>` all fall out of the same rule,
# and so does a tag the user invented, which must survive just as unchanged.
_TAG_RE = re.compile(r"<[^<>\n]{1,60}>")
# A header is a line that is only a name and a colon: `subject_definitions:`,
# `summary:`, `detailed_description:`. Matched per line so a colon inside a
# sentence is not mistaken for one.
_HEADER_RE = re.compile(r"^[ \t]*([A-Za-z_][A-Za-z0-9_ ]{0,48}):[ \t]*$", re.MULTILINE)
# Beat markers such as `[Shot 1]`.
_MARKER_RE = re.compile(r"\[[^\]\n]{1,48}\]")

_SYSTEM_EN = """\
You are a line editor for prompts written for a video-generation model. Improve
how the prompt you are given is worded, and change nothing else about it.

Keep, exactly as given:
- Every header line (a line that is only a name followed by a colon, such as
  subject_definitions:, summary:, detailed_description:) - the same headers, in
  the same order, spelled the same way.
- Every tag in angle brackets, for example <Subject 1>, <Picture 2>, <Video 1>,
  <Audio 1>, <d>...</d>. Never rename, renumber, reorder, add or remove one, and
  never point one at a different slot.
- Every bracketed beat marker such as [Shot 1], in order.
- Every claim: who does what and in what order, the camera, the lighting, the
  setting, the wardrobe, the audio policy, and every prohibition ("no second
  person", "NO MALE AUDIO", "never import the sheet's grid"). Never soften a
  prohibition and never turn a negative into a positive.
- The prompt's own language. Do not translate it.

Improve only:
- Grammar, spelling, punctuation and capitalisation.
- Word choice: concrete, specific words instead of vague ones, and one term for
  one thing instead of synonyms drifting between sentences.
- Flow: split run-on sentences, join fragments, remove repetition, and keep the
  chronological order of the beats.

Do not add sections, sentences, subjects, actions, props or details that are not
already there, and do not explain what you changed. Stay within about 10% of the
original length: this is an edit, not an expansion.

Return the whole prompt, from its first line to its last, with no preamble, no
commentary, no headings of your own and no code fences."""

_SYSTEM_ZH = """\
你是视频生成提示词的校对编辑。只改进下面这段提示词的行文，其余一切保持不变。

必须原样保留：
- 所有标题行（整行只有「名称:」的形式，例如 subject_definitions:、summary:、
  detailed_description:）——标题相同、顺序相同、拼写相同。
- 所有尖括号标签，例如 <Subject 1>、<Picture 2>、<Video 1>、<Audio 1>、<d>...</d>。
  不得改名、改编号、改变顺序、增删，也不得把它指向别的槽位。
- 所有方括号节拍标记，例如 [Shot 1]，顺序不变。
- 所有事实：谁做什么、先后顺序、机位、灯光、场景、服装、音频策略，以及每一条
  禁止项（如「no second person」「NO MALE AUDIO」「never import the sheet's grid」）。
  禁止项不得弱化，否定不得改写为肯定。
- 提示词本身的语言，不要翻译。

只能改进：
- 语法、拼写、标点与大小写。
- 用词：用具体、明确的词替代含糊的词；同一事物前后用同一称呼，不要同义词来回换。
- 行文：拆开长句、合并残句、删除重复，节拍的时间顺序保持不动。

不得新增任何段落、句子、主体、动作、道具或细节，也不要解释你改了什么。长度控制
在原文约 10% 以内：这是校对，不是扩写。

只输出完整的提示词（从第一行到最后一行），不要前言、不要说明、不要自拟标题、
不要代码块。"""

_USER_TEMPLATE_EN = """\
Polish the wording of the prompt between the markers below. Keep every header, tag,
marker and claim exactly as it is, and return the whole prompt with nothing else.

=== PROMPT START ===
{prompt}
=== PROMPT END ==="""

_USER_TEMPLATE_ZH = """\
请改进下面标记之间提示词的行文。所有标题、标签、节拍标记与全部事实保持不变，
只输出完整的提示词本身。

=== PROMPT START ===
{prompt}
=== PROMPT END ==="""

_RETRY_EN = """\
That attempt changed the structure of the prompt, which must not happen:
{problems}

Edit the ORIGINAL prompt between the markers again and keep every header, tag,
marker and claim exactly as it is. Return only the whole prompt.

=== PROMPT START ===
{prompt}
=== PROMPT END ==="""

_RETRY_ZH = """\
上一次改写改动了提示词的结构，这是不允许的：
{problems}

请重新改写下面标记之间的原始提示词，所有标题、标签、节拍标记与全部事实保持不变，
只输出完整的提示词本身。

=== PROMPT START ===
{prompt}
=== PROMPT END ==="""


def is_polish_mode(value) -> bool:
    """Is this the wording-only mode? Accepts the aliases, ignores case."""
    return str(value or "").strip().lower() in POLISH_ALIASES


def _is_zh(output_language: str | None) -> bool:
    """The same language tokens `normalize_output_language` accepts ("中文", "zh").

    Duplicated as a one-line check rather than imported so this module stays free
    of the template machinery: it only ever needs to pick an instruction string.
    """
    value = str(output_language or "").strip().lower()
    return value in ("zh", "中文", "chinese", "cn", "简体中文", "chinese (simplified)")


def _normalize_tag(tag: str) -> str:
    """Compare tags ignoring spacing and case, so `<Subject 1>` == `<SUBJECT 1>`.

    A case difference is not worth a retry: the model still points at the same
    slot, and burning another slow pass on capitalisation would cost more than it
    fixes. A *different* tag, a missing one or an invented one is a real change and
    is reported.
    """
    return re.sub(r"\s+", " ", str(tag or "").strip()).lower()


@dataclass
class Inventory:
    """What a prompt is made of, for comparing two versions of it."""

    tags: Counter
    headers: list[str]
    markers: list[str]


def inventory(text: str) -> Inventory:
    source = str(text or "")
    return Inventory(
        tags=Counter(_normalize_tag(m) for m in _TAG_RE.findall(source)),
        headers=[m.strip().lower() for m in _HEADER_RE.findall(source)],
        markers=[m.strip().lower() for m in _MARKER_RE.findall(source)],
    )


@dataclass
class PolishReport:
    """How the polished text differs from what the user wrote."""

    missing_tags: list[str] = field(default_factory=list)
    added_tags: list[str] = field(default_factory=list)
    missing_headers: list[str] = field(default_factory=list)
    added_headers: list[str] = field(default_factory=list)
    missing_markers: list[str] = field(default_factory=list)
    added_markers: list[str] = field(default_factory=list)
    retried: bool = False

    @property
    def ok(self) -> bool:
        return not any(
            (
                self.missing_tags,
                self.added_tags,
                self.missing_headers,
                self.added_headers,
                self.missing_markers,
                self.added_markers,
            )
        )

    def problems(self) -> list[str]:
        """One English line per kind of change, for a log or a retry prompt."""
        out: list[str] = []
        if self.missing_tags:
            out.append(f"tags that disappeared: {', '.join(self.missing_tags)}")
        if self.added_tags:
            out.append(f"tags that were not in the original: {', '.join(self.added_tags)}")
        if self.missing_headers:
            out.append(f"headings that disappeared: {', '.join(self.missing_headers)}")
        if self.added_headers:
            out.append(f"headings that were not in the original: {', '.join(self.added_headers)}")
        if self.missing_markers:
            out.append(f"beat markers that disappeared: {', '.join(self.missing_markers)}")
        if self.added_markers:
            out.append(
                f"beat markers that were not in the original: {', '.join(self.added_markers)}"
            )
        return out

    def summary(self) -> str:
        problems = self.problems()
        return "; ".join(problems) if problems else "structure and tags unchanged"

    def as_dict(self, *, chars_before: int | None = None, chars_after: int | None = None) -> dict:
        payload: dict = {
            "ok": self.ok,
            "retried": self.retried,
            "missing_tags": list(self.missing_tags),
            "added_tags": list(self.added_tags),
            "missing_headers": list(self.missing_headers),
            "added_headers": list(self.added_headers),
            "missing_markers": list(self.missing_markers),
            "added_markers": list(self.added_markers),
            "problems": self.problems(),
            "summary": self.summary(),
        }
        if chars_before is not None:
            payload["chars_before"] = int(chars_before)
        if chars_after is not None:
            payload["chars_after"] = int(chars_after)
        return payload


def verify_polish(original: str, polished: str) -> PolishReport:
    """Compare the structure of two versions of the same prompt.

    Counts matter, not just presence: a prompt that had `<Picture 2>` twice and
    comes back with it once lost a reference line, which is the failure this whole
    module exists to catch.
    """
    before = inventory(original)
    after = inventory(polished)
    report = PolishReport()

    for tag, count in (before.tags - after.tags).items():
        report.missing_tags.extend([tag] * count)
    for tag, count in (after.tags - before.tags).items():
        report.added_tags.extend([tag] * count)

    before_headers = Counter(before.headers)
    after_headers = Counter(after.headers)
    for name, count in (before_headers - after_headers).items():
        report.missing_headers.extend([name] * count)
    for name, count in (after_headers - before_headers).items():
        report.added_headers.extend([name] * count)

    before_markers = Counter(before.markers)
    after_markers = Counter(after.markers)
    for name, count in (before_markers - after_markers).items():
        report.missing_markers.extend([name] * count)
    for name, count in (after_markers - before_markers).items():
        report.added_markers.extend([name] * count)

    return report


def build_polish_system_prompt(output_language: str = "English") -> str:
    return _SYSTEM_ZH if _is_zh(output_language) else _SYSTEM_EN


def build_polish_user_message(prompt: str, output_language: str = "English") -> str:
    template = _USER_TEMPLATE_ZH if _is_zh(output_language) else _USER_TEMPLATE_EN
    return template.format(prompt=str(prompt or "").strip())


def build_polish_retry_message(
    prompt: str,
    report: PolishReport,
    output_language: str = "English",
) -> str:
    """Ask again, naming exactly what moved the first time.

    A generic "keep the tags" is what the first attempt already said, so the retry
    has to point at the specific tag or heading that was dropped or invented.
    """
    template = _RETRY_ZH if _is_zh(output_language) else _RETRY_EN
    problems = report.problems() or ["the wording drifted from the original"]
    bullet = "\n".join(f"- {line}" for line in problems)
    return template.format(problems=bullet, prompt=str(prompt or "").strip())


def polish_note(
    report: PolishReport,
    *,
    chars_before: int,
    chars_after: int,
) -> str:
    """What the panel should say about a polish pass, or "" when nothing happened.

    The note is only written when it carries information: a clean pass needs no
    explanation, a retry is worth one line, and a structure that changed anyway is
    worth a warning the user can act on before rendering.
    """
    if report.ok and not report.retried:
        return ""
    if report.ok:
        return (
            "One retry was needed to keep the structure and tags intact "
            f"({chars_before} -> {chars_after} characters)."
        )
    return (
        "The structure check found changes the wording pass should not make: "
        f"{report.summary()}. Review the prompt before rendering."
    )
