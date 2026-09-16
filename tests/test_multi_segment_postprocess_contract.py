"""Multi-segment + postprocess ordering contract.

The executor (`director/executor_core_legacy.py`) is a monolithic function, so
it is tested the same way as the other executor contracts: by asserting the
relative order of its call sites in the source. These assertions pin the
intended per-segment sequence and the clear-VRAM placement, so a future reorder
that breaks postprocessing fails loudly instead of shipping silently.

Intended per-segment order:

    prepare -> conditioning -> [masked replace] ->
    clear (pre-sampling, unload_models = seg_total > 1) ->
    first-pass sampling -> Global Refine -> Audio Refine -> decode ->
    [face-refine hook] -> clear (segment-end, unload_models = timeline_seg_total > 1)
"""

from pathlib import Path


def _source() -> str:
    return Path("director/executor_core_legacy.py").read_text(encoding="utf-8")


def _refine_at(source: str) -> int:
    # First apply_global_refine( is the per-segment call; the second is the
    # five-frame Source Bridge refine.
    return source.index("apply_global_refine(")


def _sample_at(source: str) -> int:
    # First sample_single_stage( is the per-segment first-pass call.
    return source.index("sample_single_stage(")


def test_no_vram_clear_between_sampling_and_global_refine():
    """The DiT must stay resident from first-pass into the refine pass."""
    source = _source()
    sample_at = _sample_at(source)
    refine_at = _refine_at(source)
    assert sample_at < refine_at
    assert "cleanup_segment_vram" not in source[sample_at:refine_at]


def test_postprocess_order_is_refine_then_audio_refine_then_decode():
    source = _source()
    refine_at = _refine_at(source)
    audio_at = source.index("sample_audio_refine_pass(")
    decode_at = source.index("_decode_av_latent(", refine_at)
    assert refine_at < audio_at < decode_at


def test_presampling_clear_uses_run_segment_count_and_precedes_sampling():
    source = _source()
    pre_at = source.index("unload_models=seg_total > 1")
    assert pre_at < _sample_at(source)


def test_segment_end_clear_uses_timeline_count_and_follows_decode():
    source = _source()
    refine_at = _refine_at(source)
    decode_at = source.index("_decode_av_latent(", refine_at)
    end_at = source.index("unload_models=timeline_seg_total > 1")
    assert decode_at < end_at


def test_face_refine_runs_after_assembly():
    source = _source()
    assembly_at = source.index("=== Assembly ===")
    face_at = source.index("apply_face_refine(")
    assert assembly_at < face_at


def test_global_refine_is_inside_the_segment_loop_before_assembly():
    source = _source()
    refine_at = _refine_at(source)
    assembly_at = source.index("=== Assembly ===")
    assert refine_at < assembly_at
