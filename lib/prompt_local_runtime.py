"""In-process GGUF inference for the prompt enhancer (no external LLM server).

Loads a model from ComfyUI's own ``models/LLM`` tree with ``llama_cpp`` and runs
chat completions inside ComfyUI's process. This replaced the Ollama/cloud
dependency: the models are ones the user already has in ComfyUI, there is no
second server to start, and unloading is a local call rather than a remote one.

Two deliberate properties:

* **Nothing heavy is imported at module load.** ``llama_cpp`` pulls in a native
  library, so it is imported on first use. That keeps the model catalog and the
  route layer importable (and testable) on a box without it.
* **A VRAM ladder, not a single attempt.** A 27B model and a resident H3
  pipeline both want the same card. Loading tries progressively cheaper
  configurations - full offload, then fewer GPU layers, then a smaller context -
  so a tight card degrades into a slower answer instead of an exception.

Blocking by nature: callers on the event loop must run this in a worker thread.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .llama_chat_template_compat import ensure_multimodal_template_helpers

# 16k is ample for prompt enhancement (a few thousand tokens in, one or two
# thousand out) and much cheaper in KV cache than the 32k used for the remote
# backends.
DEFAULT_LOCAL_CTX = int(os.environ.get("MINIMAX_H3_PE_LOCAL_N_CTX", "16384"))

# Layers offloaded to GPU on the first attempt; -1 means "all of them".
DEFAULT_GPU_LAYERS = int(os.environ.get("MINIMAX_H3_PE_LOCAL_GPU_LAYERS", "-1"))

# Qwen-VL grounding wants >=1024 image tokens: llama.cpp prints a load_hparams
# advisory recommending --image-min-tokens 1024 (ggml-org/llama.cpp#16842). 0
# keeps the model's own default; raise it when reference-image fidelity matters
# more than prefill time (it applies to the mtmd vision handlers below).
IMAGE_MIN_TOKENS = int(os.environ.get("MINIMAX_H3_PE_IMAGE_MIN_TOKENS", "0"))

# Progress reporting during a local generation. Partial GPU offload runs at a
# few tokens per second, so a silent console is the normal state of a healthy
# run - and it reads as a hang. Whichever of these comes first prints a line.
_STREAM_REPORT_SECONDS = 5.0
_STREAM_REPORT_CHUNKS = 128

log = logging.getLogger("ComfyUI-MiniMax-H3-Motion-Director.prompt_local_runtime")

# Where to send users when the engine is missing or running on CPU. The URL is
# served by this pack (see director/prompt_enhance_routes.py), so it works
# offline and for private checkouts alike.
LOCAL_SETUP_DOC = "docs/PROMPT_ENHANCER_LOCAL_SETUP.md"
LOCAL_SETUP_URL = "/minimax/motion-director/prompt_enhancer_setup"

# GPU backends llama.cpp can ship. Present in the wheel = the build can use it;
# mapped into the process = it actually loaded (see _mapped_gpu_backends).
_GPU_BACKENDS = (
    ("cuda", "libggml-cuda.so"),
    ("hip", "libggml-hip.so"),
    ("vulkan", "libggml-vulkan.so"),
    ("metal", "libggml-metal.so"),
)


def _shipped_gpu_backends() -> list[str]:
    """GPU backends the installed llama.cpp wheel contains (works on any OS)."""
    try:
        import llama_cpp

        lib_dir = Path(llama_cpp.__file__).parent / "lib"
        return [name for name, filename in _GPU_BACKENDS if (lib_dir / filename).exists()]
    except Exception:  # noqa: BLE001 - status only, never fatal
        return []


def _mapped_gpu_backends() -> list[str]:
    """GPU backends actually loaded into this process (Linux only).

    A CUDA wheel whose runtime libraries are missing still ships the backend
    file but never loads it - llama.cpp then silently falls back to the CPU
    backend. Whether the library is mapped into the process is the signal that
    separates "GPU build" from "GPU build that cannot load here".
    """
    try:
        with open("/proc/self/maps", encoding="utf-8", errors="replace") as handle:
            mapped = handle.read()
    except OSError:
        return []
    return [name for name, filename in _GPU_BACKENDS if filename in mapped]


def _classify_backend(requested_gpu_layers: int, *, after_load: bool = False) -> tuple[str, bool | None]:
    """Return (backend label, gpu_active) for a load attempt.

    Only meaningful with ``after_load=True`` (i.e. straight after constructing
    the model): before a load nothing is mapped, which says nothing about
    whether it *would* load. gpu_active stays None when the platform cannot tell
    (no /proc and a GPU backend ships), so the panel says "unknown" instead of
    guessing.
    """
    mapped = _mapped_gpu_backends()
    if mapped:
        return mapped[0], True
    if requested_gpu_layers == 0:
        return "cpu", False
    shipped = _shipped_gpu_backends()
    if not shipped:
        # The build contains no GPU code at all - safe to say on any platform.
        return "cpu", False
    if after_load and os.path.isdir("/proc/self"):
        # The backend file exists but was never mapped into the process, so its
        # load failed (typically a wheel built for a different CUDA major).
        return "cpu", False
    return shipped[0], None


_ENGINE_WARNED = False


def _context_failure_hint(message: str) -> str:
    """Translate llama-cpp-python's generic context error into the likely cause.

    ``Failed to create llama context with model. This may indicate that
    llama_context_params is out of sync with the bundled llama.cpp version...``
    is what a failed KV-cache allocation looks like from the Python wrapper - the
    same parameters succeed one rung down, so it is capacity, not a version skew.
    """
    text = str(message or "")
    hint = ""
    if "Failed to create llama context" in text:
        hint += (
            " (usually the KV cache did not fit in the free VRAM, not a version skew: "
            "the same parameters work on the next rung)"
        )
    if "raise_exception" in text or ("is undefined" in text and "jinja" in text.lower()):
        hint += (
            " (the checkpoint's chat template calls a Jinja helper the multimodal "
            "handler does not define; see llama_chat_template_compat)"
        )
    return hint


def _free_vram_gb() -> float | None:
    """Free VRAM in GB, or None when it cannot be read (best effort).

    Read through torch because it is already loaded in ComfyUI's process. A
    CPU-only build raises, and no NVIDIA-only tool is assumed to exist.
    """
    try:
        import torch  # type: ignore

        if not torch.cuda.is_available():
            return None
        free, _total = torch.cuda.mem_get_info()
        return float(free) / 1e9
    except Exception:  # noqa: BLE001 - diagnostics only, never fatal
        return None


def _model_file_gb(path: str) -> float | None:
    try:
        return Path(path).stat().st_size / 1e9
    except OSError:
        return None


def _warn_cpu_engine_once() -> None:
    """One line in the log the first time the engine is found on CPU."""
    global _ENGINE_WARNED
    if _ENGINE_WARNED:
        return
    _ENGINE_WARNED = True
    log.warning(
        "Prompt enhancer is running llama.cpp on CPU (a GPU build is typically "
        "10-50x faster). If this machine has a GPU, see %s - an NVIDIA wheel "
        "must match the CUDA runtime's major version (cu128 = CUDA 12, cu131 = "
        "CUDA 13); AMD needs a ROCm/Vulkan build or a server backend.",
        LOCAL_SETUP_DOC,
    )

_LOCACHE: dict[tuple, "LocalChat"] = {}
_LOCK = threading.RLock()


class LocalModelError(RuntimeError):
    """Raised when a local model cannot be loaded or run."""


@dataclass
class LoadAttempt:
    n_gpu_layers: int
    n_ctx: int
    reason: str


def _attempt_ladder(n_ctx: int, n_gpu_layers: int) -> list[LoadAttempt]:
    """Cheaper-and-cheaper ways to load, in order.

    Driven by what actually fails on a 24 GB card with H3 resident: running out
    of VRAM while offloading all layers, then again at full context.
    """
    tries: list[LoadAttempt] = [
        LoadAttempt(n_gpu_layers, n_ctx, "full GPU offload"),
        LoadAttempt(max(1, n_gpu_layers // 2) if n_gpu_layers > 0 else 20, n_ctx, "partial GPU offload"),
        LoadAttempt(0, max(4096, n_ctx // 2), "CPU inference with reduced context"),
    ]
    seen: set[tuple[int, int]] = set()
    out: list[LoadAttempt] = []
    for attempt in tries:
        key = (attempt.n_gpu_layers, attempt.n_ctx)
        if key in seen:
            continue
        seen.add(key)
        out.append(attempt)
    return out


def _build_handler(cls, mmproj_path: Path):
    """Instantiate an mtmd vision handler, optionally with an image-token floor.

    ``image_min_tokens`` is only passed when the env knob asks for it, and a
    handler that does not accept the keyword falls back to the plain call rather
    than failing the whole load.
    """
    if IMAGE_MIN_TOKENS > 0:
        try:
            return cls(
                clip_model_path=str(mmproj_path),
                verbose=False,
                image_min_tokens=IMAGE_MIN_TOKENS,
            )
        except TypeError:
            pass  # handler without the knob: load it the plain way
    return cls(clip_model_path=str(mmproj_path), verbose=False)


def _pick_chat_handler(model_path: Path, mmproj_path: Path | None):
    """Choose the multimodal chat handler matching the model architecture.

    The architecture comes from the GGUF metadata rather than the filename, since
    filenames in the wild are inconsistent. Text-only models get no handler, which
    lets llama.cpp apply the checkpoint's own chat template.
    """
    if mmproj_path is None:
        return None, "text-only"
    try:
        from llama_cpp import Llama
        from llama_cpp import llama_chat_format as cf
    except Exception as exc:  # noqa: BLE001
        raise LocalModelError(f"llama_cpp is unavailable: {exc}") from exc

    arch = ""
    try:
        probe = Llama(model_path=str(model_path), vocab_only=True, verbose=False)
        meta = probe.metadata or {}
        for key in ("general.architecture", "general.name"):
            value = meta.get(key)
            if value:
                arch = str(value).lower()
                break
        del probe
    except Exception:  # noqa: BLE001 - metadata is a nicety, not a requirement
        arch = model_path.stem.lower()

    handler_map = (
        ("qwen35", "Qwen35ChatHandler"),
        ("qwen3vl", "Qwen3VLChatHandler"),
        ("qwen3-vl", "Qwen3VLChatHandler"),
        ("qwen2vl", "Qwen25VLChatHandler"),
        ("qwen2.5vl", "Qwen25VLChatHandler"),
    )
    for token, attr in handler_map:
        if token.replace("-", "") in arch.replace("-", "").replace(".", ""):
            cls = getattr(cf, attr, None)
            if cls is not None:
                try:
                    return _build_handler(cls, Path(mmproj_path)), attr
                except Exception as exc:  # noqa: BLE001
                    raise LocalModelError(f"{attr} could not load {mmproj_path.name}: {exc}") from exc

    fallback = getattr(cf, "MTMDChatHandler", None)
    if fallback is not None:
        try:
            return _build_handler(fallback, Path(mmproj_path)), "MTMDChatHandler"
        except Exception as exc:  # noqa: BLE001
            raise LocalModelError(f"MTMDChatHandler could not load {mmproj_path.name}: {exc}") from exc
    return None, "no handler"


class LocalChat:
    """A loaded GGUF model plus the bookkeeping needed to reuse it."""

    def __init__(
        self,
        model_path: str,
        *,
        mmproj_path: str | None = None,
        n_ctx: int = DEFAULT_LOCAL_CTX,
        n_gpu_layers: int = DEFAULT_GPU_LAYERS,
        verbose: bool = False,
    ) -> None:
        self.model_path = str(model_path)
        self.mmproj_path = str(mmproj_path) if mmproj_path else None
        self.n_ctx = int(n_ctx)
        self.n_gpu_layers = int(n_gpu_layers)
        self.verbose = bool(verbose)
        self.llm = None
        self.handler_name = "none"
        self.loaded_with: LoadAttempt | None = None
        # Filled in by load(): which backend the model ended up on.
        self.device_backend = ""
        self.gpu_active: bool | None = None

    def load(self) -> "LocalChat":
        try:
            from llama_cpp import Llama
        except Exception as exc:  # noqa: BLE001
            raise LocalModelError(
                "llama_cpp is not installed in ComfyUI's Python environment. "
                "Install it with: pip install llama-cpp-python"
            ) from exc

        if not Path(self.model_path).is_file():
            raise LocalModelError(f"Model file not found: {self.model_path}")

        errors: list[str] = []
        ladder = _attempt_ladder(self.n_ctx, self.n_gpu_layers)
        # Before any load: the multimodal handlers render the checkpoint's own chat
        # template in an environment that lacks the helpers Transformers defines, and
        # Qwen3-VL's template calls raise_exception. Without this every vision request
        # fails with UndefinedError before generating a token.
        helper_status = ensure_multimodal_template_helpers()
        if helper_status not in ("already installed", ""):
            log.info("Chat template compatibility: %s", helper_status)
        for index, attempt in enumerate(ladder):
            handler, handler_name = (None, "none")
            try:
                if self.mmproj_path:
                    handler, handler_name = _pick_chat_handler(Path(self.model_path), Path(self.mmproj_path))
                self.llm = Llama(
                    model_path=self.model_path,
                    n_ctx=attempt.n_ctx,
                    n_gpu_layers=attempt.n_gpu_layers,
                    chat_handler=handler,
                    verbose=self.verbose,
                    logits_all=False,
                )
                self.handler_name = handler_name
                self.loaded_with = attempt
                self.device_backend, self.gpu_active = _classify_backend(
                    attempt.n_gpu_layers, after_load=True
                )
                if self.gpu_active is False and attempt.n_gpu_layers != 0:
                    _warn_cpu_engine_once()
                if index > 0:
                    # Say why the fallback happened, in the same place as the
                    # decision: a card that is busy (ComfyUI resident, a game
                    # running) cannot host the weights, and without the numbers
                    # the slowdown reads as a bug in the enhancer.
                    free_gb = _free_vram_gb()
                    model_gb = _model_file_gb(self.model_path)
                    facts = []
                    if free_gb is not None:
                        facts.append(f"free VRAM {free_gb:.1f} GB")
                    if model_gb is not None:
                        facts.append(f"model file {model_gb:.1f} GB")
                    detail = f" ({', '.join(facts)})" if facts else ""
                    print(
                        f"[PromptEnhancer] Loaded with a reduced configuration "
                        f"({attempt.reason}: {attempt.n_gpu_layers} GPU layers, {attempt.n_ctx} ctx){detail}. "
                        "Expect slower generation than a full GPU offload."
                    )
                    if errors:
                        print(f"[PromptEnhancer] why: {errors[0][:200]}{_context_failure_hint(errors[0])}")
                return self
            except Exception as exc:  # noqa: BLE001 - try the next rung
                errors.append(f"{attempt.reason}: {type(exc).__name__}: {exc}")
                self.llm = None
        raise LocalModelError("Could not load the model. " + " | ".join(errors[-3:]))

    @property
    def ready(self) -> bool:
        return self.llm is not None

    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repeat_penalty: float = 1.1,
        seed: int = -1,
    ) -> str:
        if self.llm is None:
            raise LocalModelError("Model is not loaded.")
        kwargs: dict = {
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "repeat_penalty": float(repeat_penalty),
        }
        if seed is not None and int(seed) >= 0:
            kwargs["seed"] = int(seed)

        # Streaming, not for the tokens but for the silence: a 27B on partial GPU
        # offload writes a couple of tokens a second, so a 2000-token answer is a
        # 10-20 minute wait with nothing at all in the console. That is
        # indistinguishable from a hang, and it gets reported as one.
        started = time.monotonic()
        content: list[str] = []
        reasoning: list[str] = []
        tokens = 0
        reported = 0
        reported_at = started
        next_report = started + _STREAM_REPORT_SECONDS
        usage: dict = {}
        for chunk in self.llm.create_chat_completion(stream=True, **kwargs):
            if not isinstance(chunk, dict):
                continue
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            delta = (choices[0] or {}).get("delta") if choices else None
            if not isinstance(delta, dict):
                continue
            text = delta.get("content")
            if isinstance(text, str) and text:
                content.append(text)
                tokens += 1
            think = delta.get("reasoning_content")
            if isinstance(think, str) and think:
                reasoning.append(think)
            now = time.monotonic()
            if tokens and (now >= next_report or tokens - reported >= _STREAM_REPORT_CHUNKS):
                # Rate over the reporting window, not since the start: a cumulative
                # average undersells a run once it warms up (the first line of a
                # 2 tok/s job reads "0.1 tok/s" and looks like a hang).
                window = max(1e-6, now - reported_at)
                overall = max(1e-6, now - started)
                print(
                    f"[PromptEnhancer] generating... {tokens} tokens "
                    f"({(tokens - reported) / window:.1f} tok/s now, "
                    f"{tokens / overall:.1f} tok/s average)"
                )
                next_report = now + _STREAM_REPORT_SECONDS
                reported = tokens
                reported_at = now

        elapsed = max(1e-6, time.monotonic() - started)
        generated = int(usage.get("completion_tokens") or tokens)
        prompt_tokens = usage.get("prompt_tokens")
        prompt_note = f", {int(prompt_tokens)} prompt tokens" if prompt_tokens else ""
        print(
            f"[PromptEnhancer] generated {generated} tokens in {elapsed:.1f}s "
            f"({generated / elapsed:.1f} tok/s{prompt_note})"
        )
        # Same precedence the non-streaming path had: the answer wins, reasoning is
        # the fallback for models that only fill that field.
        body = "".join(content).strip()
        return body or "".join(reasoning).strip()

    def close(self) -> None:
        self.llm = None
        try:
            import gc

            gc.collect()
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - best effort only
            pass


def cache_key(model_path: str, mmproj_path: str | None, n_ctx: int, n_gpu_layers: int) -> tuple:
    return (str(model_path), str(mmproj_path or ""), int(n_ctx), int(n_gpu_layers))


def get_local_chat(
    model_path: str,
    *,
    mmproj_path: str | None = None,
    n_ctx: int = DEFAULT_LOCAL_CTX,
    n_gpu_layers: int = DEFAULT_GPU_LAYERS,
    verbose: bool = False,
) -> LocalChat:
    """Return a loaded model, reusing the resident one when the key matches.

    Reuse matters more here than for an HTTP backend: loading a 27B from disk
    takes tens of seconds, and the panel is meant to feel like a button press.
    """
    key = cache_key(model_path, mmproj_path, n_ctx, n_gpu_layers)
    with _LOCK:
        existing = _LOCACHE.get(key)
        if existing is not None and existing.ready:
            return existing
        # A different model is resident: drop it first so we never hold two.
        for other_key, other in list(_LOCACHE.items()):
            if other_key != key:
                other.close()
                _LOCACHE.pop(other_key, None)
        chat = LocalChat(
            model_path,
            mmproj_path=mmproj_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
        )
        chat.load()
        _LOCACHE[key] = chat
        return chat


def unload_local_models() -> int:
    """Free any resident local model. Returns how many were dropped."""
    with _LOCK:
        count = len(_LOCACHE)
        for chat in list(_LOCACHE.values()):
            chat.close()
        _LOCACHE.clear()
    return count


def resident_info() -> dict:
    with _LOCK:
        for chat in _LOCACHE.values():
            if chat.ready:
                return {
                    "model_path": chat.model_path,
                    "mmproj_path": chat.mmproj_path,
                    "handler": chat.handler_name,
                    "n_ctx": chat.loaded_with.n_ctx if chat.loaded_with else chat.n_ctx,
                    "n_gpu_layers": chat.loaded_with.n_gpu_layers if chat.loaded_with else chat.n_gpu_layers,
                }
    return {}


def engine_info() -> dict:
    """Engine state for the panel: what the build ships and what actually loaded.

    Before the first load only `shipped` is known; after a load the resident
    model contributes `backend`/`gpu`, which is how a wheel that cannot load its
    GPU backend is reported instead of silently running on CPU.
    """
    with _LOCK:
        active = next((chat for chat in _LOCACHE.values() if chat.ready), None)
    info: dict = {
        "shipped": _shipped_gpu_backends(),
        "mapped": _mapped_gpu_backends(),
        "doc": LOCAL_SETUP_DOC,
        "doc_url": LOCAL_SETUP_URL,
    }
    if active is not None:
        info.update(
            {
                "backend": active.device_backend,
                "gpu": active.gpu_active,
                "model": Path(active.model_path).name,
                "n_gpu_layers": active.loaded_with.n_gpu_layers if active.loaded_with else None,
            }
        )
    return info


def runtime_available() -> tuple[bool, str]:
    """Can local inference run at all? Returns (ok, reason)."""
    try:
        import llama_cpp  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"llama_cpp not importable: {exc}"
    return True, f"llama_cpp {getattr(llama_cpp, '__version__', '?')}"


def generate(
    model_path: str,
    *,
    system_prompt: str,
    user_prompt: str,
    images_b64: list[str] | None = None,
    mmproj_path: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    top_p: float = 0.9,
    repeat_penalty: float = 1.1,
    seed: int = -1,
    n_ctx: int = DEFAULT_LOCAL_CTX,
    n_gpu_layers: int = DEFAULT_GPU_LAYERS,
) -> tuple[str | None, str | None]:
    """Run one chat completion. Returns (text, error); never raises."""
    try:
        chat = get_local_chat(
            model_path,
            mmproj_path=mmproj_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
        )
    except LocalModelError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"

    messages = build_messages(system_prompt, user_prompt, images_b64)
    try:
        text = chat.chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            seed=seed,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"Local inference failed: {type(exc).__name__}: {exc}"
    if not text.strip():
        return None, "The local model returned an empty response."
    return text, None


def build_messages(
    system_prompt: str,
    user_prompt: str,
    images_b64: list[str] | None = None,
) -> list[dict]:
    """The chat turns to send, with no empty system turn.

    An empty system turn is NOT harmless under llama.cpp's multimodal handlers: when
    the system content is empty they inject ``DEFAULT_SYSTEM_MESSAGE`` by *prepending*
    it (see ``MTMDChatHandler._process_mtmd_prompt``), which leaves two system turns
    and makes a Qwen3 checkpoint's own template raise

        TemplateError: System message must be at the beginning.

    The caption path sends no system prompt at all - the instruction is the request -
    so this is the path that hit it. Omitting the turn lets the handler add its
    default once, where it belongs.
    """
    text = str(system_prompt or "").strip()
    messages: list[dict] = []
    if text:
        messages.append({"role": "system", "content": text})
    messages.append(_user_message(user_prompt, images_b64))
    return messages


def _user_message(prompt_text: str, images_b64: list[str] | None) -> dict:
    """Build the user turn, attaching images only when the model accepts them.

    llama.cpp's multimodal handlers are served OpenAI-style: a content list of
    ``image_url`` parts followed by the text. That differs from the Ollama shape,
    which uses a sibling ``images`` array - hence a local variant here.
    """
    images = [img for img in (images_b64 or []) if img]
    if not images:
        return {"role": "user", "content": prompt_text}
    content: list[dict] = []
    for img in images:
        url = img if img.startswith("data:") else f"data:image/jpeg;base64,{img}"
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": prompt_text})
    return {"role": "user", "content": content}
