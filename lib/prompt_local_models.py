"""Local (in-ComfyUI) prompt-enhancer model catalog and discovery.

The Director's prompt enhancer used to require an external LLM server (Ollama,
llama-swap, a cloud endpoint). This module backs the local mode instead: it finds
GGUF models the user already has inside ComfyUI's own ``models`` tree, and knows
which additional quants can be fetched on demand.

Two sources are merged:

1. **Scan** - every ``.gguf`` under ComfyUI's ``LLM`` model folders, so anything the
   user dropped in themselves appears in the dropdown without configuration.
2. **Manifest** - :data:`prompt_local_catalog.json`, the curated set of quants of
   the recommended abliterated Qwen, each with a real download size so the UI can
   ask before pulling multiple gigabytes.

Sizes in the manifest are the published file sizes, used for the pre-download
confirmation and for a VRAM hint. They are approximate on purpose: the point is
"this is a 13 GB download", not byte accounting.

Deliberately dependency-light: nothing here imports torch, llama_cpp, or
ComfyUI, so the catalog can be listed (and unit tested) without a GPU or a
running ComfyUI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Where the recommended models are published.
RECOMMENDED_REPO = "huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF"

# Default quant: the largest one that still fits a 16 GB card with room for a
# KV cache. Everything else in the manifest is opt-in.
DEFAULT_MODEL_ID = "qwen3.8-27b-abl-ud-q3-k-xl"

# Sub-folder of ComfyUI's LLM models dir where on-demand downloads land, so a
# fetched model is indistinguishable from one the user placed by hand.
DOWNLOAD_SUBDIR = "MiniMaxH3-PromptEnhancer"

CATALOG_PATH = Path(__file__).with_name("prompt_local_catalog.json")


@dataclass
class LocalModel:
    """One selectable local model.

    ``path`` is set only when the weights are present on disk; otherwise the
    entry is a download candidate described by ``repo_id``/``filename``.
    """

    id: str
    label: str
    path: str = ""
    repo_id: str = ""
    filename: str = ""
    size_bytes: int = 0
    vision: bool = False
    mmproj_repo_id: str = ""
    mmproj_filename: str = ""
    mmproj_size_bytes: int = 0
    vram_gb: float = 0.0
    note: str = ""
    source: str = "scan"  # "scan" | "manifest"
    discovered_by: str = ""  # scan only: which folder it came from

    @property
    def installed(self) -> bool:
        return bool(self.path) and Path(self.path).is_file()

    @property
    def downloadable(self) -> bool:
        return bool(self.repo_id and self.filename)

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / 1e9, 2) if self.size_bytes else 0.0

    @property
    def total_download_bytes(self) -> int:
        return int(self.size_bytes) + (int(self.mmproj_size_bytes) if self.vision else 0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "path": self.path,
            "installed": self.installed,
            "downloadable": self.downloadable,
            "repo_id": self.repo_id,
            "filename": self.filename,
            "size_bytes": int(self.size_bytes),
            "size_gb": self.size_gb,
            "vision": bool(self.vision),
            "mmproj_filename": self.mmproj_filename,
            "mmproj_size_bytes": int(self.mmproj_size_bytes),
            "vram_gb": float(self.vram_gb),
            "note": self.note,
            "source": self.source,
            "discovered_by": self.discovered_by,
        }


@dataclass
class Catalog:
    models: list[LocalModel] = field(default_factory=list)
    default_id: str = DEFAULT_MODEL_ID
    errors: list[str] = field(default_factory=list)

    def get(self, model_id: str) -> LocalModel | None:
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def installed(self) -> list[LocalModel]:
        return [m for m in self.models if m.installed]

    def resolve_default(self) -> LocalModel | None:
        """The default if usable, else the first installed model.

        Never returns a not-yet-downloaded entry: the caller would have to
        silently fetch gigabytes to honour it.
        """
        preferred = self.get(self.default_id)
        if preferred and preferred.installed:
            return preferred
        for model in self.models:
            if model.installed:
                return model
        return None


def _load_manifest(path: Path | None = None) -> dict:
    catalog_path = Path(path) if path else CATALOG_PATH
    try:
        with open(catalog_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - a broken manifest must not break listing
        return {"__error__": f"Could not read {catalog_path.name}: {exc}"}
    return data if isinstance(data, dict) else {}


def manifest_models(path: Path | None = None) -> list[LocalModel]:
    """The curated downloadable set, in manifest order."""
    data = _load_manifest(path)
    out: list[LocalModel] = []
    for entry in data.get("models") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        out.append(
            LocalModel(
                id=str(entry["id"]),
                label=str(entry.get("label") or entry["id"]),
                repo_id=str(entry.get("repo_id") or ""),
                filename=str(entry.get("filename") or ""),
                size_bytes=int(entry.get("size_bytes") or 0),
                vision=bool(entry.get("vision")),
                mmproj_repo_id=str(entry.get("mmproj_repo_id") or ""),
                mmproj_filename=str(entry.get("mmproj_filename") or ""),
                mmproj_size_bytes=int(entry.get("mmproj_size_bytes") or 0),
                vram_gb=float(entry.get("vram_gb") or 0),
                note=str(entry.get("note") or ""),
                source="manifest",
            )
        )
    return out


def llm_model_roots() -> list[Path]:
    """Every directory that may hold ``LLM`` models.

    Sources are probed independently: ``get_folder_paths("LLM")`` raises
    ``KeyError`` until something registers that category, and letting that
    exception escape this function used to discard the ``models_dir`` fallback
    too - so every model the user already had went undiscovered.

    ``extra_model_paths.yaml`` is honoured because ``folder_paths`` folds those
    locations into the category once it is registered.
    """
    roots: list[Path] = []

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = Path(path)
        except (TypeError, ValueError):
            return
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)

    models_dir: Path | None = None
    try:
        import folder_paths  # type: ignore

        # Category paths: present only after ComfyUI (or another pack) registers
        # the "LLM" folder type, and this call raises rather than returning empty
        # when that has not happened yet.
        try:
            for candidate in folder_paths.get_folder_paths("LLM") or []:
                add(Path(candidate))
        except Exception:  # noqa: BLE001 - category not registered yet
            pass

        raw_models_dir = getattr(folder_paths, "models_dir", None)
        if raw_models_dir:
            models_dir = Path(raw_models_dir)
        else:
            base_path = getattr(folder_paths, "base_path", None)
            if base_path:
                models_dir = Path(base_path) / "models"
    except Exception:  # noqa: BLE001 - running outside ComfyUI entirely
        pass

    if models_dir is not None:
        add(models_dir / "LLM")

    if not roots:
        env = os.environ.get("COMFYUI_MODELS_DIR")
        if env:
            add(Path(env) / "LLM")

    return roots


def download_dir(root: Path | None = None) -> Path:
    """Where on-demand downloads are written."""
    if root is not None:
        return Path(root) / DOWNLOAD_SUBDIR
    roots = llm_model_roots()
    base = roots[0] if roots else Path(os.environ.get("COMFYUI_MODELS_DIR", "models")) / "LLM"
    return Path(base) / DOWNLOAD_SUBDIR


def scan_gguf_files(roots: list[Path] | None = None, max_depth: int = 4) -> list[tuple[Path, Path]]:
    """Find ``(.gguf path, root it was found under)`` pairs.

    Depth-limited because ``models/LLM`` trees can be deep (``Qwen-VL/<model>/GGUF/``)
    and a runaway walk over a network mount is not worth a dropdown entry.
    """
    found: list[tuple[Path, Path]] = []
    for root in roots if roots is not None else llm_model_roots():
        root = Path(root)
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            if len(current.parts) - base_depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.lower().endswith(".gguf"):
                    found.append((current / name, root))
    return found


def _looks_like_projector(path: Path) -> bool:
    """Is this the vision projector rather than a language model?

    In llama.cpp's Qwen-VL layout the projector is ``mmproj-*.gguf``; it is not
    loadable as a chat model on its own, so it must not appear in the dropdown.
    """
    return path.name.lower().startswith("mmproj")


def detect_vision(model_path: Path | str) -> bool:
    """Does a sibling vision projector make this checkpoint multimodal?

    Derived from the filesystem rather than stored state, so it holds equally for
    a scanned file and for one resolved from a stored ``local::<path>`` id - the
    latter previously lost the flag and silently dropped every reference image.
    """
    folder = Path(model_path).parent
    if not folder.is_dir():
        return False
    return any(_looks_like_projector(p) for p in folder.glob("*.gguf"))


# Preferred quantisation order when several quants of the same model are
# installed and we have to pick one without asking. Mid-range quants are the
# sweet spot: f16 doubles memory traffic for no useful quality gain at these
# sizes, and the very low quants hurt instruction-following.
_QUANT_PREFERENCE = (
    "q4_k_m",
    "iq4_xs",
    "q4_k_s",
    "q4_k_xl",
    "q5_k_m",
    "q5_k_s",
    "q3_k_xl",
    "q6_k",
    "q8_0",
    "f16",
    "bf16",
    "q3_k_m",
    "iq3_xxs",
    "q2_k",
)


def quant_rank(filename: str) -> int:
    """Lower is more preferred; unknown quantisations sort last."""
    lowered = filename.lower()
    for index, token in enumerate(_QUANT_PREFERENCE):
        if token in lowered:
            return index
    return len(_QUANT_PREFERENCE)


def scanned_models(roots: list[Path] | None = None) -> list[LocalModel]:
    """Turn discovered GGUF files into selectable entries."""
    out: list[LocalModel] = []
    for path, root in scan_gguf_files(roots):
        if _looks_like_projector(path):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        parent = path.parent.name
        rel = None
        try:
            rel = path.parent.relative_to(root)
        except ValueError:
            rel = None
        label = f"{parent} / {path.name}" if parent and parent.lower() != "gguf" else path.stem
        if rel and str(rel) not in (".", ""):
            label = f"{rel} / {path.name}"
        out.append(
            LocalModel(
                id=f"local::{path}",
                label=label,
                path=str(path),
                size_bytes=size,
                # A sibling projector means this checkpoint can accept images.
                vision=detect_vision(path),
                source="scan",
                discovered_by=str(root),
                note="found in your ComfyUI models folder",
            )
        )
    # Same model, several quants: order the preferred quant first so the automatic
    # pick does not land on whichever filename happens to sort earliest.
    out.sort(key=lambda m: (Path(m.path).parent.as_posix().lower(), quant_rank(Path(m.path).name), m.label.lower()))
    return out


def build_catalog(
    roots: list[Path] | None = None,
    manifest_path: Path | None = None,
) -> Catalog:
    """Merge scanned models with the manifest, manifest first.

    A manifest entry whose file is already on disk (in the download folder or
    anywhere else under ``models/LLM``) is marked installed rather than offered
    for download again - otherwise a user who placed the file by hand would be
    prompted to fetch 13 GB they already have.
    """
    catalog = Catalog()
    manifest = manifest_models(manifest_path)

    by_name: dict[str, Path] = {}
    for path, _root in scan_gguf_files(roots):
        by_name.setdefault(path.name.lower(), path)

    for entry in manifest:
        installed = by_name.get(entry.filename.lower())
        if installed is not None:
            entry.path = str(installed)
        else:
            # Not found by name: look for it in the download folder specifically,
            # in case it was renamed by a previous partial fetch.
            candidate = download_dir(roots[0] if roots else None) / entry.filename
            if candidate.is_file():
                entry.path = str(candidate)
        catalog.models.append(entry)

    manifest_names = {m.filename.lower() for m in manifest if m.filename}
    for scanned in scanned_models(roots):
        if Path(scanned.path).name.lower() in manifest_names:
            continue  # already represented by its manifest entry
        catalog.models.append(scanned)

    data = _load_manifest(manifest_path)
    if data.get("__error__"):
        catalog.errors.append(str(data["__error__"]))
    catalog.default_id = str(data.get("default") or DEFAULT_MODEL_ID)
    return catalog


def resolve_local_model(model_id: str, roots: list[Path] | None = None) -> LocalModel | None:
    """Resolve a selection (manifest id, raw path, or filename) to a usable model."""
    if not model_id:
        return None
    raw = str(model_id).strip()
    if raw.startswith("local::"):
        raw = raw[len("local::") :]

    candidate = Path(raw)
    if candidate.is_file() and candidate.suffix.lower() == ".gguf":
        return LocalModel(
            id=model_id,
            label=candidate.stem,
            path=str(candidate),
            size_bytes=_safe_size(candidate),
            vision=detect_vision(candidate),
            source="scan",
        )

    catalog = build_catalog(roots)
    match = catalog.get(raw)
    if match is not None:
        return match if match.installed else None

    lowered = raw.lower()
    for model in catalog.models:
        if model.filename and model.filename.lower() == lowered:
            return model if model.installed else None
        if model.path and Path(model.path).stem.lower() == lowered:
            return model if model.installed else None
    return None


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def find_vision_projector(model_path: Path) -> Path | None:
    """Locate the ``mmproj`` projector that pairs with a model file."""
    folder = Path(model_path).parent
    if not folder.is_dir():
        return None
    candidates = [p for p in folder.glob("*.gguf") if _looks_like_projector(p)]
    if not candidates:
        return None
    # Prefer a projector whose name shares the model's quant family.
    stem = Path(model_path).stem.lower()
    for candidate in candidates:
        token = "bf16" if "q8" in stem or "fp16" in stem else ""
        if token and token in candidate.name.lower():
            return candidate
    return sorted(candidates, key=lambda p: p.name)[0]


def free_disk_bytes(path: Path) -> int:
    """Usable bytes on the volume holding ``path`` (0 when unknown)."""
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        import shutil

        return int(shutil.disk_usage(probe).free)
    except Exception:  # noqa: BLE001
        return 0
