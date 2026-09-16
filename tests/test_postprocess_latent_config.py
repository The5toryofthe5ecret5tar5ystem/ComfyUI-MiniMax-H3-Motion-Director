from director.postprocess_config import (
    POSTPROCESS_CONFIG_VERSION,
    normalize_postprocess_config,
    postprocess_cache_fingerprint,
)


def test_learned_latent_config_normalizes_and_is_cache_relevant():
    cfg = normalize_postprocess_config(
        {
            "global_refine": {
                "enabled": True,
                "mode": "upscale",
                "upscale_method": "h3_learned_latent",
                "latent_upscale_model": "h3_upscale.safetensors",
                "latent_upscale_variant": "3D",  # legacy value must be discarded
                "latent_upscale_precision": "BF16",
                "latent_upscale_device": "CPU",
            }
        }
    )
    g = cfg["global_refine"]
    assert POSTPROCESS_CONFIG_VERSION >= 9
    assert g["upscale_method"] == "h3_learned_latent"
    assert g["latent_upscale_model"] == "h3_upscale.safetensors"
    assert "latent_upscale_variant" not in g
    assert g["latent_upscale_precision"] == "bf16"
    assert g["latent_upscale_device"] == "cpu"
    fingerprint = postprocess_cache_fingerprint(cfg)
    assert fingerprint["global_refine"]["latent_upscale_model"] == "h3_upscale.safetensors"
    assert "latent_upscale_variant" not in fingerprint["global_refine"]


def test_old_config_keeps_existing_pixel_default_without_manual_latent_variant():
    cfg = normalize_postprocess_config(
        {"version": 1, "global_refine": {"enabled": True, "latent_upscale_variant": "2d"}}
    )
    assert cfg["global_refine"]["upscale_method"] == "lanczos"
    assert "latent_upscale_variant" not in cfg["global_refine"]
    assert cfg["global_refine"]["latent_upscale_precision"] == "fp16"
    assert cfg["global_refine"]["latent_upscale_device"] == "cuda"


def test_resident_upscaler_flag_is_off_by_default():
    """Opt-in only: keeping the upscaler resident holds VRAM for the session."""
    cfg = normalize_postprocess_config({})
    assert cfg["global_refine"]["latent_upscale_cache_model"] is False

    off = normalize_postprocess_config(
        {"global_refine": {"latent_upscale_cache_model": False}}
    )
    assert off["global_refine"]["latent_upscale_cache_model"] is False


def test_resident_upscaler_flag_parses_truthy_values():
    for raw in (True, "on", "1", "true"):
        cfg = normalize_postprocess_config(
            {"global_refine": {"latent_upscale_cache_model": raw}}
        )
        assert cfg["global_refine"]["latent_upscale_cache_model"] is True, raw


def test_resident_flag_does_not_invalidate_the_first_pass_cache():
    """It changes how fast the upscale runs, not the frames it produces."""
    base = {"global_refine": {"upscale_method": "h3_learned_latent"}}
    off = postprocess_cache_fingerprint(normalize_postprocess_config(base))
    on = postprocess_cache_fingerprint(
        normalize_postprocess_config(
            {"global_refine": {"upscale_method": "h3_learned_latent", "latent_upscale_cache_model": True}}
        )
    )
    assert off == on
