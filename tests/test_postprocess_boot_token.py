"""The postprocess UI module must carry a cache-busting boot token.

ComfyUI caches frontend modules by URL, so a changed ``minimax_postprocess_ui.mjs``
is only re-served when the ``?boot=`` token on the import changes.  This is the
Python-side twin of ``web/js/tests/minimax_postprocess_bootstrap.test.mjs``:
both exist so a forgotten bump fails in whichever suite a contributor runs.

Bump ``EXPECTED_BOOT_TOKEN`` whenever ``minimax_postprocess_ui.mjs`` changes.
"""

from pathlib import Path

EXPECTED_BOOT_TOKEN = "postprocess_output_v11"


def test_postprocess_module_boot_token_is_current():
    timeline = Path("web/js/minimax_timeline.js").read_text(encoding="utf-8")
    assert f"minimax_postprocess_ui.mjs?boot={EXPECTED_BOOT_TOKEN}" in timeline, (
        "minimax_postprocess_ui.mjs changed; bump the ?boot= token in "
        "web/js/minimax_timeline.js and EXPECTED_BOOT_TOKEN here."
    )
