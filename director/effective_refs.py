"""Per-segment R2V Common/Local reference compilation.

The timeline stores stable semantic asset IDs.  Official MiniMax tags are a
runtime presentation detail and are rebuilt for every segment from its actual
selected Common assets followed by its Local assets.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


SEMANTIC_TOKEN_RE = re.compile(
    r"\{\{mmx-ref:(picture|video|audio):([A-Za-z0-9_.:-]+)\}\}",
    re.IGNORECASE,
)


class SemanticReferenceError(ValueError):
    """A semantic prompt reference cannot be resolved for this segment."""


@dataclass(frozen=True)
class EffectiveReferences:
    pictures: list[Any]
    videos: list[Any]
    audios: list[Any]
    video_audios: list[Any]
    tags: dict[tuple[str, str], str]


def semantic_reference_token(kind: str, asset_id: str) -> str:
    key = str(kind or "").strip().lower()
    identity = str(asset_id or "").strip()
    if key not in {"picture", "video", "audio"}:
        raise ValueError("Semantic reference kind must be picture, video, or audio.")
    if not identity or not re.fullmatch(r"[A-Za-z0-9_.:-]+", identity):
        raise ValueError("Semantic reference asset ID is empty or contains unsafe characters.")
    return f"{{{{mmx-ref:{key}:{identity}}}}}"


def _asset_id(item: Any) -> str:
    return str(getattr(item, "asset_id", "") or "").strip()


def _renumber(items: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for index, item in enumerate(items):
        cloned = copy.copy(item)
        cloned.index = index
        out.append(cloned)
    return out


def _selected(items: Iterable[Any], selected_ids: set[str]) -> list[Any]:
    return [item for item in items if _asset_id(item) in selected_ids]


def _paired_for_videos(video_audios: Iterable[Any], videos: list[Any]) -> list[Any]:
    """Return paired soundtracks in effective video order.

    A paired audio shares the stable asset ID of its Video asset.  ``index`` is
    rewritten to the Video input index because the official node looks up
    ``ref_video_audio_N`` by ``ref_video_N``.
    """
    by_asset = {_asset_id(item): item for item in video_audios if _asset_id(item)}
    out: list[Any] = []
    for video in videos:
        asset_id = _asset_id(video)
        paired = by_asset.get(asset_id)
        if paired is None:
            continue
        cloned = copy.copy(paired)
        cloned.index = int(video.index)
        out.append(cloned)
    return out


def compile_effective_references(
    *,
    common_pictures: Iterable[Any] = (),
    common_videos: Iterable[Any] = (),
    common_audios: Iterable[Any] = (),
    common_video_audios: Iterable[Any] = (),
    selected_common_asset_ids: set[str] | frozenset[str] = frozenset(),
    local_pictures: Iterable[Any] = (),
    local_videos: Iterable[Any] = (),
    local_audios: Iterable[Any] = (),
    local_video_audios: Iterable[Any] = (),
) -> EffectiveReferences:
    """Build effective references and exact official prompt-tag mapping.

    Ordering is deterministic: selected Common assets in pool order, then Local
    assets in segment order.  Picture/Video slots are independently dense.
    Official Audio numbering is paired Video soundtracks first (Video order),
    then standalone Audio assets, matching ``MiniMaxH3ReferenceToVideo``.
    """
    selected_ids = {str(value) for value in selected_common_asset_ids}
    pictures = _renumber(
        [*_selected(common_pictures, selected_ids), *list(local_pictures)]
    )
    videos = _renumber(
        [*_selected(common_videos, selected_ids), *list(local_videos)]
    )
    audios = _renumber(
        [*_selected(common_audios, selected_ids), *list(local_audios)]
    )
    selected_common_video_audios = _selected(common_video_audios, selected_ids)
    video_audios = _paired_for_videos(
        [*selected_common_video_audios, *list(local_video_audios)], videos
    )

    tags: dict[tuple[str, str], str] = {}
    for item in pictures:
        if _asset_id(item):
            tags[("picture", _asset_id(item))] = f"<Picture {int(item.index) + 1}>"
    for item in videos:
        if _asset_id(item):
            tags[("video", _asset_id(item))] = f"<Video {int(item.index) + 1}>"

    audio_number = 1
    for item in video_audios:
        if _asset_id(item):
            tags[("audio", _asset_id(item))] = f"<Audio {audio_number}>"
        audio_number += 1
    for item in audios:
        if _asset_id(item):
            tags[("audio", _asset_id(item))] = f"<Audio {audio_number}>"
        audio_number += 1

    return EffectiveReferences(
        pictures=pictures,
        videos=videos,
        audios=audios,
        video_audios=video_audios,
        tags=tags,
    )


def compile_semantic_prompt(
    prompt: str | None,
    tags: Mapping[tuple[str, str], str],
    *,
    known_assets: Mapping[tuple[str, str], str] | None = None,
    segment_label: str = "Segment",
) -> str:
    """Replace semantic tokens with official tags or fail on disabled assets."""
    text = str(prompt or "")
    known = known_assets or {}

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        asset_id = match.group(2)
        key = (kind, asset_id)
        official = tags.get(key)
        if official is not None:
            return official
        label = known.get(key)
        pretty_kind = {"picture": "Picture", "video": "Video", "audio": "Audio"}[kind]
        if label:
            raise SemanticReferenceError(
                f'{segment_label} prompt references {label} ({pretty_kind} asset "{asset_id}"), '
                "but that asset is disabled for this segment. Re-enable it or remove "
                "the corresponding prompt reference."
            )
        raise SemanticReferenceError(
            f'{segment_label} prompt references unknown {pretty_kind} asset "{asset_id}". '
            "Restore the asset or remove the corresponding prompt reference."
        )

    return SEMANTIC_TOKEN_RE.sub(replace, text)


def resolve_semantic_tokens(
    prompt: str | None,
    tags: Mapping[tuple[str, str], str],
) -> str:
    """Resolve the semantic tokens that this segment can, keep the rest as written.

    ``compile_semantic_prompt`` raises on an unknown or disabled asset, which is
    right for the prompt-batch builder: it owns the whole prompt and can demand a
    fix before the render. The video timeline cannot make that demand - its prompts
    can outlive the asset pool, and a render should not die because a mention lost
    its file - so unknown tokens are left alone rather than guessed at, while known
    ones become this segment's official tag so the numbering matches the
    references that will actually be sent.
    """
    def replace(match: re.Match[str]) -> str:
        key = (match.group(1).lower(), match.group(2))
        return tags.get(key) or match.group(0)

    return SEMANTIC_TOKEN_RE.sub(replace, str(prompt or ""))


__all__ = [
    "EffectiveReferences",
    "SEMANTIC_TOKEN_RE",
    "SemanticReferenceError",
    "compile_effective_references",
    "compile_semantic_prompt",
    "resolve_semantic_tokens",
    "semantic_reference_token",
]
