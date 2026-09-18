# Prompt enhancer: local engine setup (llama.cpp)

The panel's **Local (ComfyUI models)** mode runs a GGUF model inside ComfyUI's
Python process through `llama-cpp-python` — no Ollama server, no external
process. That dependency is what this page is about.

## What the panel tells you

Under the Model row the panel shows the engine state:

| Status | Meaning |
| --- | --- |
| `Engine: GPU (CUDA)` | the GPU backend loaded; inference runs on the GPU |
| `Engine: CPU only` | llama.cpp fell back to the CPU backend — works, but 10-50x slower |
| `Engine: llama.cpp not installed` | the package is missing from ComfyUI's Python |

`CPU only` is the important one: llama.cpp **silently** falls back to CPU when
its GPU backend cannot load, so without this line the only symptom is speed.

## The one hard rule for NVIDIA wheels

A prebuilt wheel is tagged with the CUDA version it was compiled against
(`cu128` = CUDA 12.8, `cu131` = CUDA 13.1). Its GPU backend (`libggml-cuda.so`)
declares an exact runtime dependency, and only the **major** version matters:

```text
cu128 wheel → needs libcudart.so.12 / libcublas.so.12   (CUDA 12.x, any minor)
cu131 wheel → needs libcudart.so.13 / libcublas.so.13   (CUDA 13.x, any minor)
```

The two are not interchangeable (different sonames by design). The minor version
is free: a `cu131` wheel runs on CUDA 13.4; a `cu128` wheel runs on 12.4 or 12.9.
The driver must be at least the runtime's major (driver 610 runs both).

Check what CUDA runtime the machine provides:

```bash
ldconfig -p | grep libcudart        # Linux: system toolkit
nvidia-smi                          # driver version
nvcc --version                      # toolkit version, if installed
```

If the CUDA runtime libraries are missing entirely, a CUDA wheel still installs
and still reports itself as CUDA — the backend just never loads, and llama.cpp
uses the CPU. That is the failure this page exists for.

## Install options

### NVIDIA, Linux/Windows

1. Look at the CUDA major the machine can provide (`ldconfig -p`, `nvcc`,
   `/opt/cuda`).
2. Install the matching wheel from
   [JamePeng/llama-cpp-python releases](https://github.com/JamePeng/llama-cpp-python/releases/)
   (`cu126`/`cu128` for CUDA 12, `cu131` for CUDA 13; python tag must match
   ComfyUI's Python, e.g. `cp312`):

   ```bash
   python_embeded/bin/python -m pip install --force-reinstall --no-deps \
     <wheel-url-from-the-releases-page>
   ```

3. Alternative: keep a CUDA-12 wheel and supply the runtime libraries through
   pip instead of the system toolkit
   (`pip install nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 nvidia-nccl-cu12`,
   then make them visible to the loader, e.g. by symlinking the `.so` files next
   to `llama_cpp/lib/`).
4. The plain **CPU wheel** from PyPI works everywhere — it is just slow.

Restart ComfyUI after changing the package.

### AMD (Linux, ROCm)

- Prebuilt wheels exist on the official llama-cpp-python index:
  `rocm72` (`0.3.27`) and `vulkan` (`0.3.26`), published as `py3-none`, so they
  fit any Python 3 version:

  ```bash
  python_embeded/bin/python -m pip install --force-reinstall --no-deps \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/rocm72 \
    llama-cpp-python
  ```

  These are older than the NVIDIA fork build used above; **verify the vision
  handlers exist** before relying on them:

  ```bash
  python_embeded/bin/python -c "from llama_cpp.llama_chat_format import Qwen25VLChatHandler; print('handlers OK')"
  ```

- Or build from source against ROCm:
  `CMAKE_ARGS="-DGGML_HIPBLAS=on" pip install llama-cpp-python`.
- Windows/other AMD: use the **Vulkan** build
  (`CMAKE_ARGS="-DGGML_VULKAN=on"`, or the official `vulkan` wheel), which runs
  on AMD, NVIDIA and Intel.

### macOS

Build with Metal (default in llama.cpp builds) or use Ollama, which is the
lowest-friction option there.

### No local engine at all — the zero-install routes

The same panel has three backends that need nothing installed in ComfyUI:

- **Ollama** (`http://127.0.0.1:11434`) — runs on NVIDIA, AMD (ROCm) and macOS
  (Metal).
- **OpenAI Compatible** (`/v1/chat/completions`) — llama.cpp's `llama-server`,
  LM Studio, koboldcpp, vLLM, or any remote endpoint.
- **Zhipu GLM** — cloud API.

Switch the API dropdown; the local engine is only needed for `Local (ComfyUI models)`.

## Why this is not automatic

The pack cannot ship one wheel that fits every machine: CUDA wheels are tied to
a CUDA major, AMD needs ROCm or Vulkan, and macOS needs Metal. The panel reports
what it loaded instead of guessing, and this page is the lookup table. If the
engine reports `CPU only` and you are unsure, the safest universal option is the
plain CPU wheel — correct everywhere, just slower.
