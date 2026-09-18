"""MiniMax H3 runs at a fixed 24 fps - one place that knows it.

H3 has no fps input: **the frame count is the duration**, and the model's joint
video+audio latent is defined at 24 fps. ComfyUI's own H3 nodes say so ("Duration
snaps to the model's 17k+5 frame grid at 24 fps"; a ref2va reference video is
"Reference video frames at 24 fps (2-15s)").

A project may still be *authored* at another rate - a 30 fps source is common -
and the timeline, the window bounds and a frames-keyed mask are all addressed in
that source's frames, so `plan.frame_rate` stays the source rate. What must not
follow it is anything that turns a frame count into seconds for the *output*:

* the segment audio is padded/trimmed to the picture, which is 24 fps content;
* the node's ``fps`` output stamps the muxed video.

Both used ``plan.frame_rate`` and therefore disagreed with the picture in a
30 fps project: the audio came out at ``frames/30`` (a silent 20% tail) and the
merged export played 25% fast, while the per-segment clips were written at 24.

The remaining, unfixed consequence is speed: N frames of 30 fps footage handed to
a 24 fps model play 25% slow. Fixing that needs the frames resampled - and the
mask resampled in lockstep - so this module only makes the rates consistent and
lets ``rate_warning_message`` tell the user what an off-rate project will do.
"""

from __future__ import annotations

from typing import Any

H3_MODEL_FPS = 24.0


def readable_fps(value: Any) -> float:
    """The project/source rate, defaulting to the model rate when unreadable."""
    try:
        fps = float(value)
    except (TypeError, ValueError):
        return H3_MODEL_FPS
    return fps if fps > 0 else H3_MODEL_FPS


def is_off_rate(value: Any) -> bool:
    """True when the project rate differs from the model's."""
    return abs(readable_fps(value) - H3_MODEL_FPS) >= 0.01


def rate_direction(value: Any) -> tuple[float, str]:
    """``(ratio, 'slow'|'fast')`` for a project rate against the model's."""
    ratio = readable_fps(value) / H3_MODEL_FPS
    return ratio, ("slow" if ratio > 1 else "fast")


def rate_warning_message(value: Any) -> str:
    """One paragraph: what an off-rate project does, and what to do about it."""
    fps = readable_fps(value)
    ratio, direction = rate_direction(fps)
    return (
        f"Project frame rate is {fps:g} fps, but MiniMax H3 generates at a fixed "
        f"{H3_MODEL_FPS:g} fps - the frame count is the duration, and there is no fps "
        "input (ComfyUI's own H3 nodes document both). Frames are passed to the model as "
        f"they are, so this project's picture plays {ratio:.2f}x {direction}: a window of N "
        f"source frames lasts N/{H3_MODEL_FPS:g} s rather than N/{fps:g} s, and a duration "
        f"typed in seconds lands on the model's {H3_MODEL_FPS:g} fps. The segment audio and "
        f"the merged export stay at the model's {H3_MODEL_FPS:g} fps, so picture and sound "
        f"keep together. Recommended: use a {H3_MODEL_FPS:g} fps source video for the "
        f"footage whose character is being replaced - a {fps:g} fps source needs resampling "
        "for the timing to be exact."
    )


def rate_report_note(value: Any) -> str:
    """Short line for the run report; empty when the project is already 24 fps."""
    if not is_off_rate(value):
        return ""
    fps = readable_fps(value)
    ratio, direction = rate_direction(fps)
    return (
        f"Frame rate: project is {fps:g} fps but H3 runs at {H3_MODEL_FPS:g} fps - this "
        f"render plays {ratio:.2f}x {direction}. Use a {H3_MODEL_FPS:g} fps source for "
        "exact timing."
    )


__all__ = [
    "H3_MODEL_FPS",
    "is_off_rate",
    "rate_direction",
    "rate_report_note",
    "rate_warning_message",
    "readable_fps",
]
