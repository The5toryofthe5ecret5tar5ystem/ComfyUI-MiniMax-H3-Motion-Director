#!/usr/bin/env python3
"""MiniMax H3 Motion Director - QA readiness sweep.

One command that answers "is this build actually ready to use, and what is
wrong with it?" for the whole custom-node pack: node classes, Python backend,
frontend modules, the contracts between them, the user-facing flow, and
(optionally) a live ComfyUI instance.

    python scripts/qa_readiness.py              # static sweep + both suites
    python scripts/qa_readiness.py --live       # + probe a running ComfyUI
    python scripts/qa_readiness.py --fast       # static only, skip the suites
    python scripts/qa_readiness.py --only frontend,contracts

Reports are written to ``artifacts/qa_readiness_report.{json,md}`` and a summary
is printed to stdout. Exit code is 0 when nothing reached the fail threshold
(default: ERROR), 1 when it did, 2 when the sweep itself could not run.

Why this exists next to ``pytest`` and ``npm test``
---------------------------------------------------
The suites prove individual behaviours. They cannot tell you:

* whether the copy ComfyUI actually loads matches the copy you edited;
* whether a frontend module still resolves every import it declares;
* whether two modules are loaded twice under different ``?boot=`` tokens
  (two instances, two stylesheets, two sets of listeners);
* whether the frontend calls an endpoint that no longer exists;
* whether a backend event is emitted into the void because nothing listens;
* whether a translation key was added to one locale only;
* how much of the UI text never reaches the translator at all.

Those are the failure modes that cost the most time, because every one of them
looks like "the feature silently did nothing". Each check below is written so
that it can actually fail.

Checks are heuristics where noted (regex/AST over source); the report labels
which are exact and which are advisory.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Severity + layers
# --------------------------------------------------------------------------- #

BLOCKER = "BLOCKER"
ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"
SUGGESTION = "SUGGESTION"

SEVERITY_ORDER = [BLOCKER, ERROR, WARNING, INFO, SUGGESTION]
SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITY_ORDER)}

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

# Layers are also the columns of the readiness matrix.
LAYER_TOOLCHAIN = "toolchain"
LAYER_SUITES = "suites"
LAYER_BACKEND = "backend"
LAYER_FRONTEND = "frontend"
LAYER_CONTRACTS = "contracts"
LAYER_I18N = "i18n"
LAYER_FLOW = "flow"
LAYER_LIVE = "live"

LAYERS = [
    (LAYER_TOOLCHAIN, "Build & toolchain"),
    (LAYER_BACKEND, "Python backend"),
    (LAYER_FRONTEND, "Frontend modules"),
    (LAYER_SUITES, "Test suites"),
    (LAYER_CONTRACTS, "Cross-boundary contracts"),
    (LAYER_I18N, "Localization"),
    (LAYER_FLOW, "User-facing flow"),
    (LAYER_LIVE, "Live runtime"),
]

# "exact" checks are derived from parsed source / real process output, so a
# failure is a real defect. "advice" checks are heuristics intended to point at
# places worth a look, never to gate a release on their own.
KIND_EXACT = "exact"
KIND_ADVICE = "advice"

PLUGIN_DIR_NAME = "ComfyUI-MiniMax-H3-Motion-Director"

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "artifacts",
}

# Files whose differences between the dev checkout and the ComfyUI install copy
# are expected and harmless (per-machine state, generated reports).
DRIFT_IGNORED_SUFFIXES = ("qa_readiness_report.json", "qa_readiness_report.md")


# --------------------------------------------------------------------------- #
# Result model
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    severity: str
    layer: str
    title: str
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "layer": self.layer,
            "title": self.title,
            "detail": self.detail,
            "evidence": self.evidence[:40],
            "hint": self.hint,
        }


@dataclass
class Check:
    cid: str
    layer: str
    title: str
    fn: object
    kind: str = KIND_EXACT
    reason: str = ""  # why it was skipped


@dataclass
class Context:
    repo: Path
    install: Path | None
    comfy_root: Path | None
    python: str
    node: str
    args: argparse.Namespace
    findings: list[Finding] = field(default_factory=list)
    check_status: dict[str, str] = field(default_factory=dict)
    check_note: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)
    started: float = field(default_factory=time.time)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def note(self, message: str) -> None:
        self.notes.append(message)


CHECKS: list[Check] = []


def check(cid: str, layer: str, title: str, kind: str = KIND_EXACT):
    """Register a check. The function receives the Context and returns a
    (status, note) tuple. Raising is contained by the runner."""

    def decorator(fn):
        CHECKS.append(Check(cid=cid, layer=layer, title=title, fn=fn, kind=kind))
        return fn

    return decorator


# --------------------------------------------------------------------------- #
# Process + source helpers
# --------------------------------------------------------------------------- #


def run(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: int = 1800,
) -> tuple[int, str, str]:
    """Run a command, never raise. Returns (returncode, stdout, stderr)."""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=merged,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return 124, out, (err + f"\n[timed out after {timeout}s]")
    except FileNotFoundError as exc:
        return 127, "", f"{exc}"
    except Exception as exc:  # noqa: BLE001 - a broken probe must not end the sweep
        return 126, "", f"{exc}"


def walk(source: Path, suffixes: tuple[str, ...], skip_dirs: tuple[str, ...] = ()) -> list[Path]:
    """Every matching file under `source`, skipping vendored/generated trees."""
    found: list[Path] = []
    for root, dirs, files in os.walk(source):
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDED_DIRS
            and d not in skip_dirs
            and not d.startswith(".deploy-backup")
        ]
        for name in files:
            if name.endswith(suffixes):
                found.append(Path(root) / name)
    return sorted(found)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def md5_of(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def js_block(src: str, open_idx: int) -> str:
    """Return the balanced {...} block starting at `open_idx`, string-aware.

    A naive brace count breaks on the many URLs, templates and regexes in this
    codebase, so quotes, template literals and comments are skipped properly.
    """
    depth = 0
    i = open_idx
    n = len(src)
    quote = ""
    while i < n:
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = src[i + 1]
            if nxt == "/":
                j = src.find("\n", i)
                i = n if j == -1 else j + 1
                continue
            if nxt == "*":
                j = src.find("*/", i)
                i = n if j == -1 else j + 2
                continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx : i + 1]
        i += 1
    return src[open_idx:]


# Frontend module specifiers: `import x from "..."`, `import("...")`,
# `export { x } from "..."`.
JS_MODULE_SPEC = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*)(["'])([^"'`\n]+)\1""", re.M
)

# ComfyUI's helper is the norm here; plain fetch() is used a handful of times.
JS_ENDPOINT = re.compile(
    r"""(?:\bfetchApi|\bfetch)\s*\(\s*(?:`([^`]*)`|"([^"]*)"|'([^']*)')""", re.M
)

PY_EVENT_NAME = re.compile(r"""["'](minimax_motion_director_[a-z_]+)["']""")
JS_EVENT_LISTEN = re.compile(
    r"""addEventListener\s*\(\s*["'](minimax_motion_director_[a-z_]+)["']"""
)


def js_module_candidates(spec: str, importer: Path) -> list[Path]:
    """Candidate on-disk paths for a relative module specifier, best first."""
    clean = spec.split("?", 1)[0].split("#", 1)[0]
    if not clean.startswith("."):
        return []
    base = (importer.parent / clean).resolve()
    out = [base]
    if base.suffix not in (".js", ".mjs", ".json"):
        out += [base.with_suffix(".js"), base.with_suffix(".mjs")]
    out += [
        base / "index.js",
        base / "index.mjs",
    ]
    return out


def resolve_js_module(spec: str, importer: Path) -> Path | None:
    """Resolve a relative module specifier to a file on disk, or None."""
    for candidate in js_module_candidates(spec, importer):
        if candidate.is_file():
            return candidate
    return None


def escapes_pack_web(spec: str, importer: Path, repo: Path) -> bool:
    """Is this specifier reaching outside the pack's own frontend tree?

    ComfyUI serves ``web/js`` at ``/extensions/<pack>/``, so a specifier with
    enough ``..`` segments (``../../scripts/app.js``) addresses ComfyUI's own web
    root at runtime. Those cannot be checked against this checkout, and are not
    defects when the file is missing here.
    """
    clean = spec.split("?", 1)[0].split("#", 1)[0]
    if not clean.startswith("."):
        return False
    target = (importer.parent / clean).resolve()
    web_root = (repo / "web").resolve()
    try:
        target.relative_to(web_root)
    except ValueError:
        return True
    return False


def external_url(spec: str) -> str | None:
    """The HTTP path a specifier escaping the pack resolves to at runtime.

    ``../../scripts/app.js`` from ``/extensions/<pack>/x.js`` is
    ``/scripts/app.js``. Each leading ``../`` pops one segment off the served
    directory, which starts two deep.
    """
    clean = spec.split("?", 1)[0].split("#", 1)[0]
    segments = ["extensions", PLUGIN_DIR_NAME]
    rest = clean
    while rest.startswith("../"):
        rest = rest[3:]
        if segments:
            segments.pop()
    parts = segments + [part for part in rest.split("/") if part not in (".", "")]
    if not parts:
        return None
    return "/" + "/".join(parts)


# --------------------------------------------------------------------------- #
# Layer: toolchain
# --------------------------------------------------------------------------- #


@check("tc_python", LAYER_TOOLCHAIN, "Python interpreter is usable")
def tc_python(ctx: Context):
    rc, out, err = run([ctx.python, "-c", "import sys;print(sys.version)"])
    if rc != 0:
        ctx.add(
            Finding(
                BLOCKER,
                LAYER_TOOLCHAIN,
                "Python interpreter cannot run",
                err.strip()[:400],
                hint="Pass --python /path/to/python (the ComfyUI embedded one).",
            )
        )
        return STATUS_FAIL, "interpreter failed"
    version = out.strip().split(" ")[0]
    ctx.metrics["python_version"] = version
    major, minor = (int(p) for p in version.split(".")[:2])
    if (major, minor) < (3, 10):
        ctx.add(
            Finding(
                ERROR,
                LAYER_TOOLCHAIN,
                f"Python {version} is below the declared floor (>=3.10)",
                "pyproject.toml declares requires-python >=3.10.",
            )
        )
        return STATUS_FAIL, f"python {version}"
    return STATUS_PASS, f"python {version}"


@check("tc_extras", LAYER_TOOLCHAIN, "Optional external tools present")
def tc_extras(ctx: Context):
    missing = []
    for tool, why in (
        ("ffmpeg", "segment export / probe fallback"),
        ("sox", "audio post-processing"),
    ):
        if shutil.which(tool) is None:
            missing.append(f"{tool} ({why})")
    ctx.metrics["external_tools_missing"] = missing
    if missing:
        ctx.add(
            Finding(
                WARNING,
                LAYER_TOOLCHAIN,
                "External binaries not on PATH",
                "These are auto-detected; the features that need them are "
                "skipped or degraded at runtime rather than failing loudly: "
                + ", ".join(missing),
                hint="Install them if you want those features exercised.",
            )
        )
        return STATUS_WARN, ", ".join(missing)
    return STATUS_PASS, "ffmpeg + sox found"


@check("tc_comfy_root", LAYER_TOOLCHAIN, "ComfyUI checkout discovered")
def tc_comfy_root(ctx: Context):
    if ctx.comfy_root is None:
        ctx.add(
            Finding(
                WARNING,
                LAYER_TOOLCHAIN,
                "No ComfyUI checkout found",
                "Checks that import comfy/folder_paths/server are skipped, which "
                "covers backend route enumeration and node-class validation.",
                hint="Pass --comfy-root /path/to/ComfyUI to enable them.",
            )
        )
        return STATUS_SKIP, "not found"
    if not (ctx.comfy_root / "folder_paths.py").is_file():
        ctx.add(
            Finding(
                ERROR,
                LAYER_TOOLCHAIN,
                "The path given as ComfyUI root does not look like a checkout",
                f"{ctx.comfy_root} has no folder_paths.py.",
            )
        )
        return STATUS_FAIL, str(ctx.comfy_root)
    return STATUS_PASS, str(ctx.comfy_root)


@check("tc_comfy_import", LAYER_TOOLCHAIN, "ComfyUI + torch import in the target interpreter")
def tc_comfy_import(ctx: Context):
    if ctx.comfy_root is None:
        return STATUS_SKIP, "no comfy root"
    code = (
        "import json,torch;"
        "import comfy.model_management as mm;"
        "print(json.dumps({'torch':torch.__version__,"
        "'cuda':bool(torch.cuda.is_available()),"
        "'device':str(torch.cuda.get_device_name(0)) if torch.cuda.is_available() else ''}))"
    )
    rc, out, err = run(
        [ctx.python, "-c", code],
        cwd=ctx.comfy_root,
        env={"PYTHONPATH": str(ctx.comfy_root)},
        timeout=300,
    )
    if rc != 0:
        ctx.add(
            Finding(
                ERROR,
                LAYER_TOOLCHAIN,
                "ComfyUI/torch could not be imported by the target interpreter",
                err.strip()[-600:],
                hint="Use the interpreter that runs ComfyUI (--python).",
            )
        )
        return STATUS_FAIL, "import failed"
    try:
        payload = json.loads(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return STATUS_PASS, out.strip()[:80]
    ctx.metrics["torch"] = payload
    if not payload.get("cuda"):
        ctx.add(
            Finding(
                WARNING,
                LAYER_TOOLCHAIN,
                "torch reports no CUDA device",
                f"torch {payload.get('torch')} imported, but "
                "torch.cuda.is_available() is False. GPU checks and live probes "
                "that need a device will not be meaningful.",
            )
        )
        return STATUS_WARN, f"torch {payload.get('torch')}, no CUDA"
    return STATUS_PASS, f"torch {payload.get('torch')} on {payload.get('device')}"


def is_runtime_file(relative: Path) -> bool:
    """Does ComfyUI actually load this file while running the pack?

    Only runtime drift changes behaviour. Tests, docs, example workflows and CI
    config routinely differ between a working checkout and an install copy, and
    reporting those at the same severity drowns the signal that matters.
    """
    parts = relative.parts
    if not parts:
        return False
    head = parts[0]
    if head in ("nodes", "director", "patches", "lib"):
        return True
    if head == "web":
        if len(parts) > 1 and parts[1] == "js":
            return "tests" not in parts
        return False
    return relative.name in ("__init__.py", "requirements.txt", "pyproject.toml")


@check("tc_drift", LAYER_TOOLCHAIN, "Dev checkout matches the ComfyUI install copy")
def tc_drift(ctx: Context):
    """The single highest-value check on this machine.

    The install copy is what ComfyUI loads; the dev checkout is what gets
    edited. When they diverge, every symptom is observed from code that is not
    the code being read.
    """
    if ctx.install is None:
        return STATUS_SKIP, "no install copy given"
    if not ctx.install.is_dir():
        return STATUS_SKIP, f"{ctx.install} is not a directory"

    rc, out, _ = run(["git", "ls-files"], cwd=ctx.repo, timeout=120)
    if rc == 0 and out.strip():
        tracked = [Path(line) for line in out.splitlines() if line.strip()]
    else:
        tracked = [
            p.relative_to(ctx.repo)
            for p in walk(ctx.repo, (".py", ".js", ".mjs", ".json", ".md", ".toml", ".ini", ".txt"))
        ]

    runtime_differs: list[str] = []
    runtime_absent: list[str] = []
    other_differs: list[str] = []
    other_absent: list[str] = []
    compared = 0
    for relative in tracked:
        if relative.name.endswith(DRIFT_IGNORED_SUFFIXES):
            continue
        src = ctx.repo / relative
        if not src.is_file():
            continue
        dst = ctx.install / relative
        runtime = is_runtime_file(relative)
        if not dst.is_file():
            (runtime_absent if runtime else other_absent).append(str(relative))
            continue
        compared += 1
        if md5_of(src) != md5_of(dst):
            (runtime_differs if runtime else other_differs).append(str(relative))

    ctx.metrics["drift"] = {
        "compared": compared,
        "runtime_differing": runtime_differs,
        "runtime_absent": runtime_absent,
        "other_differing": other_differs,
        "other_absent": other_absent,
    }

    if runtime_differs or runtime_absent:
        detail = []
        if runtime_differs:
            detail.append(f"{len(runtime_differs)} runtime file(s) differ from the dev checkout")
        if runtime_absent:
            detail.append(
                f"{len(runtime_absent)} runtime file(s) exist in dev but not in the install copy"
            )
        ctx.add(
            Finding(
                ERROR,
                LAYER_TOOLCHAIN,
                "Install copy is not running the code in this checkout",
                "; ".join(detail)
                + ". ComfyUI loads the install copy, so any symptom you observe "
                "comes from code that may not be the code you are reading.",
                evidence=[
                    f"differs: {r}" for r in runtime_differs[:25]
                ]
                + [f"absent: {r}" for r in runtime_absent[:25]],
                hint=f"Deploy {ctx.repo} -> {ctx.install}, then re-run to confirm.",
            )
        )

    if other_differs or other_absent:
        ctx.add(
            Finding(
                INFO,
                LAYER_TOOLCHAIN,
                "Non-runtime files differ between checkout and install copy",
                "Tests, docs, examples and CI config. ComfyUI never loads these, "
                "so they do not affect behaviour - but a stale test file in the "
                "install copy means `pytest` there is not testing the same suite.",
                evidence=[
                    f"{len(other_differs)} differ, {len(other_absent)} absent "
                    "(examples: "
                    + ", ".join((other_differs + other_absent)[:5])
                    + ")"
                ],
            )
        )

    if runtime_differs or runtime_absent:
        return STATUS_FAIL, f"{len(runtime_differs)} runtime differ, {len(runtime_absent)} absent"
    if other_differs or other_absent:
        return STATUS_WARN, "runtime in sync; non-runtime drift only"
    return STATUS_PASS, f"{compared} files identical"


# --------------------------------------------------------------------------- #
# Layer: backend
# --------------------------------------------------------------------------- #


@check("be_compile", LAYER_BACKEND, "Every Python module compiles")
def be_compile(ctx: Context):
    bad: list[str] = []
    count = 0
    for path in walk(ctx.repo, (".py",)):
        count += 1
        source = read_text(path)
        try:
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            bad.append(f"{rel(path, ctx.repo)}:{exc.lineno}: {exc.msg}")
    ctx.metrics["python_files"] = count
    if bad:
        ctx.add(
            Finding(
                BLOCKER,
                LAYER_BACKEND,
                "Python syntax errors",
                "ComfyUI cannot load the pack at all while these exist.",
                evidence=bad[:20],
            )
        )
        return STATUS_FAIL, f"{len(bad)} file(s)"
    return STATUS_PASS, f"{count} modules"


@check("be_node_mappings", LAYER_BACKEND, "Registered node classes are complete")
def be_node_mappings(ctx: Context):
    if ctx.comfy_root is None:
        return STATUS_SKIP, "no comfy root"
    probe = """
import json, sys, types

comfy_root, repo = sys.argv[1], sys.argv[2]
sys.path.insert(0, comfy_root)

# Load the pack as a package under an alias. Importing it as top-level `nodes`
# would collide with ComfyUI's own `nodes.py` module (a file, not a package), and
# `import nodes.director_output` would then fail on the module, not the pack.
alias = "mmx_director_under_test"
package = types.ModuleType(alias)
package.__path__ = [repo]
sys.modules[alias] = package

out = []
for module, cls in (
    ("nodes.director_output", "MiniMaxH3MotionDirector"),
    ("nodes.director_inputs", "MiniMaxH3MotionDirectorInputs"),
    ("nodes.director_inputs", "MiniMaxH3MotionDirectorAssets"),
):
    entry = {"module": module, "class": cls}
    try:
        mod = __import__(alias + "." + module, fromlist=[cls])
        klass = getattr(mod, cls)
    except Exception as exc:
        entry["error"] = f"{type(exc).__name__}: {exc}"
        out.append(entry)
        continue
    missing = [a for a in ("INPUT_TYPES", "RETURN_TYPES", "FUNCTION", "CATEGORY") if not hasattr(klass, a)]
    entry["missing_attrs"] = missing
    try:
        spec = klass.INPUT_TYPES()
        required = list((spec.get("required", {}) or {}).keys())
        optional = list((spec.get("optional", {}) or {}).keys())
        entry["inputs"] = {"required": len(required), "optional": len(optional)}
        entry["input_names"] = required + optional
    except Exception as exc:
        entry["input_types_error"] = f"{type(exc).__name__}: {exc}"
    entry["returns"] = len(getattr(klass, "RETURN_TYPES", ()) or ())
    entry["outputs"] = len(getattr(klass, "RETURN_NAMES", ()) or ())
    out.append(entry)
print(json.dumps(out))
"""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "probe_nodes.py"
        script.write_text(probe, encoding="utf-8")
        rc, out, err = run(
            [ctx.python, str(script), str(ctx.comfy_root), str(ctx.repo)],
            cwd=ctx.comfy_root,
            env={"PYTHONPATH": str(ctx.comfy_root)},
            timeout=600,
        )
    if rc != 0:
        ctx.add(
            Finding(
                ERROR,
                LAYER_BACKEND,
                "Could not import the node classes",
                err.strip()[-600:],
            )
        )
        return STATUS_FAIL, "import failed"
    try:
        payload = json.loads(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return STATUS_SKIP, "unparsable probe output"

    ctx.metrics["node_classes"] = payload
    broken = [e for e in payload if e.get("error") or e.get("missing_attrs") or e.get("input_types_error")]
    if broken:
        ctx.add(
            Finding(
                BLOCKER,
                LAYER_BACKEND,
                "A node class is not loadable or is missing required attributes",
                "ComfyUI refuses to register a node without INPUT_TYPES / "
                "RETURN_TYPES / FUNCTION / CATEGORY, and the whole pack can "
                "fail to register with it.",
                evidence=[
                    json.dumps(
                        {
                            k: e.get(k)
                            for k in ("class", "error", "missing_attrs", "input_types_error")
                            if e.get(k)
                        }
                    )
                    for e in broken
                ],
            )
        )
        return STATUS_FAIL, f"{len(broken)} class(es)"

    summary = ", ".join(
        f"{e['class'].replace('MiniMaxH3MotionDirector', 'Director')}"
        f"={e.get('inputs', {}).get('required', '?')}req/{e.get('returns', '?')}out"
        for e in payload
    )
    return STATUS_PASS, summary


@check("be_blocking_io", LAYER_FLOW, "Async handlers avoid blocking file I/O", kind=KIND_ADVICE)
def be_blocking_io(ctx: Context):
    """Blocking calls inside `async def` stall the single ComfyUI event loop.

    Wrapped calls (to_thread / run_in_executor) are exempt.
    """
    blocking_attr = {"exists", "read_text", "read_bytes", "stat", "is_file", "is_dir", "iterdir", "glob"}
    hits: list[str] = []
    for path in walk(ctx.repo / "director", (".py",)):
        source = read_text(path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                name = ""
                if isinstance(inner.func, ast.Name):
                    name = inner.func.id
                elif isinstance(inner.func, ast.Attribute):
                    name = inner.func.attr
                    if name not in blocking_attr:
                        continue
                if name == "open" or name in blocking_attr:
                    # Skip anything handed to a worker thread.
                    parent_text = lines[max(0, inner.lineno - 3) : inner.end_lineno + 1]
                    joined = "\n".join(parent_text)
                    if "to_thread" in joined or "run_in_executor" in joined or "asyncio.to_thread" in joined:
                        continue
                    hits.append(f"{rel(path, ctx.repo)}:{inner.lineno} in async {node.name}() -> {name}()")
    if hits:
        ctx.add(
            Finding(
                SUGGESTION,
                LAYER_FLOW,
                "Blocking file I/O inside async handlers",
                f"{len(hits)} call site(s) perform synchronous filesystem work on "
                "the event loop. Harmless for small files, but a large video "
                "probe or a network path (SMB mounts) can stall every other "
                "queued request while it runs.",
                evidence=hits[:20],
                hint="Wrap in asyncio.to_thread() if the path can be slow or remote.",
            )
        )
        return STATUS_WARN, f"{len(hits)} site(s)"
    return STATUS_PASS, "none found"


# --------------------------------------------------------------------------- #
# Layer: frontend
# --------------------------------------------------------------------------- #


def frontend_files(ctx: Context) -> list[Path]:
    root = ctx.repo / "web" / "js"
    return [p for p in walk(root, (".js", ".mjs")) if "tests" not in p.parts]


@check("fe_syntax", LAYER_FRONTEND, "Every frontend module parses")
def fe_syntax(ctx: Context):
    files = frontend_files(ctx)
    if shutil.which("node") is None and not Path(ctx.node).exists():
        return STATUS_SKIP, "node not available"
    bad: list[str] = []
    for path in files:
        rc, _, err = run([ctx.node, "--check", str(path)], timeout=60)
        if rc != 0:
            first = next((ln for ln in err.strip().splitlines() if ln.strip()), "")
            bad.append(f"{rel(path, ctx.repo)}: {first}")
    ctx.metrics["frontend_files"] = len(files)
    if bad:
        ctx.add(
            Finding(
                BLOCKER,
                LAYER_FRONTEND,
                "Frontend module(s) fail to parse",
                "ComfyUI serves these as native ES modules, so a syntax error "
                "takes down every feature in the file (and anything importing "
                "it) with no server-side error at all.",
                evidence=bad[:20],
            )
        )
        return STATUS_FAIL, f"{len(bad)} of {len(files)}"
    return STATUS_PASS, f"{len(files)} modules"


@check("fe_imports", LAYER_FRONTEND, "Every relative import resolves to a file")
def fe_imports(ctx: Context):
    unresolved: list[str] = []
    external: list[str] = []
    total = 0
    for path in frontend_files(ctx):
        source = read_text(path)
        for match in JS_MODULE_SPEC.finditer(source):
            spec = match.group(2)
            if not spec.startswith("."):
                continue
            total += 1
            line = source.count("\n", 0, match.start()) + 1
            where = f"{rel(path, ctx.repo)}:{line} -> {spec}"
            if any(c.is_file() for c in js_module_candidates(spec, path)):
                continue
            if escapes_pack_web(spec, path, ctx.repo):
                external.append(where)
                continue
            unresolved.append(where)

    ctx.metrics["frontend_imports"] = total
    ctx.metrics["frontend_external_imports"] = external
    if external:
        # These address ComfyUI's own frontend, which recent ComfyUI ships as a
        # built bundle rather than loose files - so a filesystem search finds
        # nothing even when the URL serves fine. Only the live server can settle
        # it, so ask the server when there is one.
        specifiers = sorted({entry.rsplit("-> ", 1)[-1] for entry in external})
        if ctx.args.live:
            broken: list[str] = []
            for spec in specifiers:
                url = external_url(spec)
                if not url:
                    continue
                status, _ = http_get(f"{ctx.args.url.rstrip('/')}{url}", timeout=15)
                if status != 200:
                    broken.append(f"{spec} -> {url} HTTP {status or 'error'}")
            if broken:
                ctx.add(
                    Finding(
                        ERROR,
                        LAYER_FRONTEND,
                        "Frontend imports into ComfyUI's own tree do not resolve",
                        "These specifiers leave the pack and are served by "
                        "ComfyUI itself. A 404 means the import graph breaks "
                        "before the pack's code runs.",
                        evidence=broken[:15],
                    )
                )
        else:
            ctx.note(
                f"{len(specifiers)} frontend import(s) address ComfyUI's own "
                "frontend ("
                + ", ".join(specifiers[:4])
                + ") and were not verified: run with --live to check them."
            )
    if unresolved:
        ctx.add(
            Finding(
                ERROR,
                LAYER_FRONTEND,
                "Frontend imports point at files that do not exist",
                "ES module resolution is exact: a typo'd or renamed path is a "
                "hard 404 at runtime, and the importing module dies silently "
                "from the user's point of view.",
                evidence=unresolved[:25],
            )
        )
        return STATUS_FAIL, f"{len(unresolved)} of {total}"
    return STATUS_PASS, f"{total} imports ({len(external)} external to ComfyUI)"


@check("fe_boot_tokens", LAYER_FRONTEND, "Shared modules load under one identity")
def fe_boot_tokens(ctx: Context):
    """ES modules are keyed by full URL including the query string.

    Importing one module as both ``./x.js`` and ``./x.js?boot=token`` - or under
    two different tokens - instantiates it twice. Two instances means two sets
    of module-level state, two stylesheets, and listeners that fire twice, which
    presents as duplicated UI or doubled actions.
    """
    per_module: dict[str, dict[str, list[str]]] = {}
    for path in frontend_files(ctx):
        source = read_text(path)
        for match in JS_MODULE_SPEC.finditer(source):
            spec = match.group(2)
            if not spec.startswith("."):
                continue
            target = resolve_js_module(spec, path)
            if target is None:
                continue
            key = rel(target, ctx.repo)
            token = ""
            if "?boot=" in spec:
                token = spec.split("?boot=", 1)[1].split("&", 1)[0]
            line = source.count("\n", 0, match.start()) + 1
            per_module.setdefault(key, {}).setdefault(token, []).append(
                f"{rel(path, ctx.repo)}:{line}"
            )

    problems: list[str] = []
    for module, tokens in sorted(per_module.items()):
        if len(tokens) > 1:
            described = ", ".join(
                f"{token or '(no token)'} x{len(where)}" for token, where in sorted(tokens.items())
            )
            problems.append(
                f"{module}: loaded {len(tokens)} different ways -> {described}; "
                f"e.g. {tokens[sorted(tokens)[0]][0]} vs "
                f"{tokens[sorted(tokens)[-1]][0]}"
            )
    ctx.metrics["boot_token_conflicts"] = problems
    if problems:
        ctx.add(
            Finding(
                ERROR,
                LAYER_FRONTEND,
                "A module is loaded under more than one URL",
                "Each distinct URL (including ?boot=...) is a separate module "
                "instance with its own module-level state. Guards written as "
                "module-local flags then run twice, which shows up as duplicated "
                "panels, doubled handlers, or a control that acts on a stale copy.",
                evidence=problems[:20],
                hint="Give every importer of the module the same ?boot= token, or drop the token everywhere.",
            )
        )
        return STATUS_FAIL, f"{len(problems)} module(s)"
    return STATUS_PASS, f"{len(per_module)} shared modules, one identity each"


@check("fe_orphans", LAYER_FRONTEND, "No shared library module is unreferenced", kind=KIND_ADVICE)
def fe_orphans(ctx: Context):
    """Only ``.mjs`` libraries are considered.

    ComfyUI auto-imports every top-level ``.js`` file in a ``WEB_DIRECTORY``, so
    those are entry points whether or not anything imports them; ``.mjs`` files
    are not auto-loaded, so an unimported one is genuinely unreachable.
    """
    files = frontend_files(ctx)
    referenced: set[str] = set()
    for path in files:
        source = read_text(path)
        for match in JS_MODULE_SPEC.finditer(source):
            target = resolve_js_module(match.group(2), path)
            if target:
                referenced.add(str(target))

    orphans = [
        rel(path, ctx.repo)
        for path in files
        if path.suffix == ".mjs" and str(path) not in referenced
    ]
    if orphans:
        ctx.add(
            Finding(
                INFO,
                LAYER_FRONTEND,
                "Library module(s) nothing imports",
                ".mjs files are not auto-loaded by ComfyUI, so nothing can reach "
                "these. Either dead code, or reached by an absolute "
                "/extensions/ path this scan cannot see.",
                evidence=orphans[:25],
            )
        )
        return STATUS_WARN, f"{len(orphans)} unreferenced"
    return STATUS_PASS, "no orphan libraries"


# --------------------------------------------------------------------------- #
# Layer: suites
# --------------------------------------------------------------------------- #


@check("su_python", LAYER_SUITES, "Python test suite")
def su_python(ctx: Context):
    env = {}
    cwd = ctx.repo
    if ctx.comfy_root is not None:
        env["PYTHONPATH"] = str(ctx.comfy_root)
        cwd = ctx.comfy_root
    rc, out, err = run(
        [
            ctx.python,
            "-m",
            "pytest",
            # No -q here: pytest.ini already sets it, and passing it twice (-qq)
            # suppresses the final summary line entirely, which would leave the
            # counts unparsed and the run reporting "0 passed" as a pass.
            "--tb=line",
            "-rf",
            "-p",
            "no:warnings",
            str(ctx.repo / "tests"),
        ],
        cwd=cwd,
        env=env,
        timeout=int(ctx.args.suite_timeout),
    )
    text = out + "\n" + err
    counts = {name: int(value) for value, name in re.findall(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)", text)}
    failed_ids = re.findall(r"^FAILED (\S+)", text, re.M)
    detail = [
        ln.strip()
        for ln in text.splitlines()
        if re.match(r"^/\S+\.py:\d+:", ln.strip())
    ]
    ctx.metrics["pytest"] = {
        "returncode": rc,
        "counts": counts,
        "failed": failed_ids[:30],
    }
    if rc == 124:
        ctx.add(
            Finding(
                BLOCKER,
                LAYER_SUITES,
                "Python suite timed out",
                f"Exceeded {ctx.args.suite_timeout}s. A hung test usually means "
                "a real wait (network, GPU, or a lock) rather than slow code.",
            )
        )
        return STATUS_FAIL, "timeout"
    if not counts:
        # Never let an unparsable run look green: that is the exact failure this
        # whole sweep exists to catch.
        ctx.add(
            Finding(
                WARNING,
                LAYER_SUITES,
                "Could not read the Python suite summary",
                "pytest exited but its counts could not be parsed, so this check "
                "proves nothing about the suite. The captured output tail is "
                "below.",
                evidence=[ln for ln in text.splitlines()[-15:] if ln.strip()],
                hint="Run pytest by hand to see what it actually printed.",
            )
        )
        return STATUS_SKIP, "summary unparsable (exit %d)" % rc
    total = sum(counts.get(k, 0) for k in ("passed", "failed", "error", "errors"))
    if counts.get("error", 0) or counts.get("errors", 0):
        ctx.add(
            Finding(
                ERROR,
                LAYER_SUITES,
                "Python suite has collection/teardown errors",
                "Tests that never ran cannot vouch for anything.",
                evidence=detail[:20],
            )
        )
        return STATUS_FAIL, f"{counts.get('errors', counts.get('error', 0))} error(s)"
    if counts.get("failed", 0):
        ctx.add(
            Finding(
                ERROR,
                LAYER_SUITES,
                f"{counts['failed']} Python test(s) failing",
                "Each is either a real regression or a test that needs updating; "
                "run with -x and full tracebacks to tell which.",
                evidence=[f"FAILED {name}" for name in failed_ids[:20]] + detail[:20],
            )
        )
        return STATUS_FAIL, f"{counts['failed']} of {total} failing"
    return STATUS_PASS, f"{total} passed"


@check("su_js", LAYER_SUITES, "Frontend test suite")
def su_js(ctx: Context):
    runner = ctx.repo / "scripts" / "run_js_tests.mjs"
    if not runner.is_file():
        return STATUS_SKIP, "no runner"
    if shutil.which("node") is None and not Path(ctx.node).exists():
        return STATUS_SKIP, "node not available"
    rc, out, err = run(
        [ctx.node, str(runner)], cwd=ctx.repo, timeout=int(ctx.args.suite_timeout)
    )
    text = out + "\n" + err
    summary = re.search(r"JS tests: (\d+)/(\d+) passed \((\d+) skipped", text)
    failed = re.findall(r"^\[FAIL\] (\S+)", text, re.M)
    skipped = re.findall(r"^\[SKIP\] (\S+)", text, re.M)
    ctx.metrics["js_tests"] = {
        "returncode": rc,
        "failed": failed,
        "skipped": skipped,
    }
    if failed or rc != 0:
        ctx.add(
            Finding(
                ERROR,
                LAYER_SUITES,
                "Frontend tests failing",
                "These exercise real UI state machines (model, undo, resume, "
                "mask, replacement) without a browser.",
                evidence=[f"FAIL {name}" for name in failed[:20]]
                or [ln for ln in text.splitlines()[-25:] if ln.strip()],
            )
        )
        return STATUS_FAIL, f"{len(failed)} failing"
    if skipped:
        ctx.note(
            f"{len(skipped)} frontend test(s) skipped: they import ComfyUI's own "
            "web/scripts/api.js, which only exists in a full checkout."
        )
    if summary:
        passed, total, skip_count = (
            int(summary.group(1)),
            int(summary.group(2)),
            int(summary.group(3)),
        )
        return STATUS_PASS, f"{passed}/{total} passed ({skip_count} skipped)"
    if not failed:
        ctx.add(
            Finding(
                WARNING,
                LAYER_SUITES,
                "Could not read the frontend suite summary",
                "The runner exited 0 but printed no parseable summary, so this "
                "check proves nothing about the frontend suite.",
                evidence=[ln for ln in text.splitlines()[-15:] if ln.strip()],
            )
        )
        return STATUS_SKIP, "summary unparsable"
    return STATUS_PASS, "passed"


# --------------------------------------------------------------------------- #
# Layer: contracts
# --------------------------------------------------------------------------- #


ROUTE_PROBE = r'''
import json, sys, types
repo, comfy = sys.argv[1], sys.argv[2]
sys.path.insert(0, comfy if comfy else repo)

# Load the pack as a package under an alias, exactly as ComfyUI does. Importing
# `director` as a top-level module instead breaks the pack's own `..lib` relative
# imports ("attempted relative import beyond top-level package") - which would
# report route enumeration as unavailable rather than reporting the real table.
alias = "mmx_routes_under_test"
package = types.ModuleType(alias)
package.__path__ = [repo]
sys.modules[alias] = package
http_routes = __import__(alias + ".director.http_routes", fromlist=["register_routes"])


class Recorder:
    def __init__(self):
        self.routes = []

    def add_route(self, method, path, handler=None):
        self.routes.append([str(method).upper(), str(path)])
        return self

    def _factory(self, method):
        def decorator(path):
            def inner(handler):
                self.routes.append([method, str(path)])
                return handler
            return inner
        return decorator

    def get(self, path=None):
        return self._factory("GET")(path)

    def post(self, path=None):
        return self._factory("POST")(path)

    def patch(self, path=None):
        return self._factory("PATCH")(path)

    def delete(self, path=None):
        return self._factory("DELETE")(path)


recorder = Recorder()
http_routes.PromptServer = type("PromptServer", (), {"instance": types.SimpleNamespace(routes=recorder)})
http_routes._ROUTES_REGISTERED = False
ok = http_routes.register_routes()
print(json.dumps({"registered": bool(ok), "routes": recorder.routes}))
'''


def segment_match(route_path: str, fe_path: str) -> bool:
    """Does a frontend path prefix plausibly address this route?

    Route segments in braces (``{preset_id}``) match anything. The frontend path
    is truncated at its first interpolation, so it may be shorter than the route.
    """
    route_segments = [s for s in route_path.strip("/").split("/") if s]
    fe_segments = [s for s in fe_path.strip("/").split("/") if s]
    if not fe_segments:
        return False
    for index, segment in enumerate(fe_segments):
        if index >= len(route_segments):
            return False
        expected = route_segments[index]
        if expected.startswith("{") and expected.endswith("}"):
            continue
        if expected != segment:
            return False
    return True


@check("ct_routes", LAYER_CONTRACTS, "Frontend endpoints have backend routes")
def ct_routes(ctx: Context):
    if ctx.comfy_root is None:
        return STATUS_SKIP, "no comfy root"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "probe_routes.py"
        script.write_text(ROUTE_PROBE, encoding="utf-8")
        rc, out, err = run(
            [ctx.python, str(script), str(ctx.repo), str(ctx.comfy_root)],
            cwd=ctx.comfy_root,
            env={"PYTHONPATH": str(ctx.comfy_root)},
            timeout=300,
        )
    if rc != 0:
        ctx.add(
            Finding(
                WARNING,
                LAYER_CONTRACTS,
                "Could not enumerate backend routes",
                err.strip()[-400:],
                hint="Route/endpoint matching is unavailable for this run.",
            )
        )
        return STATUS_SKIP, "probe failed"
    try:
        payload = json.loads(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return STATUS_SKIP, "unparsable probe output"

    routes = payload.get("routes", [])
    ctx.metrics["routes"] = routes

    # Frontend call sites, truncated at the first interpolation. Only paths this
    # pack owns are compared: ComfyUI's own core routes (/interrupt, /history,
    # /prompt, ...) are served by the host and are not ours to validate.
    calls: dict[str, list[str]] = {}
    for path in frontend_files(ctx):
        source = read_text(path)
        for match in JS_ENDPOINT.finditer(source):
            raw = next((g for g in match.groups() if g), "")
            if not raw.startswith("/minimax/"):
                continue
            for cut in ("${", "?", "#"):
                if cut in raw:
                    raw = raw.split(cut, 1)[0]
            if not raw:
                continue
            line = source.count("\n", 0, match.start()) + 1
            calls.setdefault(raw.rstrip("/") or "/", []).append(
                f"{rel(path, ctx.repo)}:{line}"
            )

    dead: list[str] = []
    for fe_path, where in sorted(calls.items()):
        if not any(segment_match(route_path, fe_path) for _, route_path in routes):
            dead.append(f"{fe_path}  (called at {where[0]})")

    used_routes = [
        f"{method} {path}"
        for method, path in routes
        if any(segment_match(path, fe_path) for fe_path in calls)
    ]
    unused_routes = [
        f"{method} {path}"
        for method, path in routes
        if f"{method} {path}" not in used_routes
    ]
    ctx.metrics["dead_endpoints"] = dead
    ctx.metrics["unused_routes"] = unused_routes

    if dead:
        ctx.add(
            Finding(
                ERROR,
                LAYER_CONTRACTS,
                "Frontend calls an endpoint with no backend route",
                "The request 404s. Depending on how the caller handles it, the "
                "user either sees a generic failure or (worse) nothing at all.",
                evidence=dead[:25],
                hint="Either the route was renamed/removed, or the path string drifted.",
            )
        )
    if unused_routes:
        ctx.add(
            Finding(
                INFO,
                LAYER_CONTRACTS,
                "Backend routes no frontend call site was found for",
                "Reached only by other tools/scripts, or dead. Not a defect on "
                "its own - listed so a rename does not go unnoticed.",
                evidence=unused_routes[:25],
            )
        )
    if dead:
        return STATUS_FAIL, f"{len(dead)} dead endpoint(s)"
    return STATUS_PASS, f"{len(routes)} routes, {len(calls)} frontend call sites"


@check("ct_events", LAYER_CONTRACTS, "Emitted events have listeners (and vice versa)")
def ct_events(ctx: Context):
    emitted: dict[str, list[str]] = {}
    # Tests are excluded: an event name quoted in a test fixture is not an
    # emitter, and counting it produces phantom "nobody is listening" findings.
    for path in walk(ctx.repo, (".py",), skip_dirs=("tests",)):
        source = read_text(path)
        for match in PY_EVENT_NAME.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            emitted.setdefault(match.group(1), []).append(
                f"{rel(path, ctx.repo)}:{line}"
            )
    listened: dict[str, list[str]] = {}
    for path in frontend_files(ctx):
        source = read_text(path)
        for match in JS_EVENT_LISTEN.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            listened.setdefault(match.group(1), []).append(
                f"{rel(path, ctx.repo)}:{line}"
            )

    ctx.metrics["events"] = {"emitted": sorted(emitted), "listened": sorted(listened)}
    # No events at all means the scan is wrong, not that the code is fine.
    if not emitted and not listened:
        return STATUS_SKIP, "no event names found"

    orphans = [f"{name} (emitted at {emitted[name][0]})" for name in sorted(emitted) if name not in listened]
    unheard = [f"{name} (listened at {listened[name][0]})" for name in sorted(listened) if name not in emitted]
    if orphans or unheard:
        ctx.add(
            Finding(
                WARNING,
                LAYER_CONTRACTS,
                "Event names do not line up across the boundary",
                "Events are strings, so a rename on one side fails silently: the "
                "backend keeps sending, the UI just never reacts.",
                evidence=[f"emitted, nobody listening: {o}" for o in orphans[:15]]
                + [f"listening, nobody emitting: {u}" for u in unheard[:15]],
            )
        )
        return STATUS_WARN, f"{len(orphans)} orphan, {len(unheard)} unheard"
    return STATUS_PASS, f"{len(emitted)} events matched both ways"


# --------------------------------------------------------------------------- #
# Layer: i18n
# --------------------------------------------------------------------------- #

I18N_MODULES = (
    ("web/js/minimax_i18n.js", "ZH", "EN"),
    ("web/js/minimax_material_library_i18n.mjs", "ZH", "EN"),
    ("web/js/minimax_mixed_i18n.mjs", "ZH", "EN"),
)

PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")

# The three locale modules in this pack do not share one style:
#   minimax_i18n.js                    const ZH = { "toolbar.add": "..." }   (quoted, dotted, one per line)
#   minimax_mixed_i18n.mjs             const ZH = Object.freeze({ "mixed.x": "..." })
#   minimax_material_library_i18n.mjs  const ZH = { button: "...", title: "..." } (bare keys, several per line)
# A parser that only understands the first silently reports the other two as
# empty, which turns their parity check into a no-op that always passes.
LOCALE_PAIR = re.compile(
    r"""(?:"([^"\n]+)"|'([^'\n]+)'|([A-Za-z_$][A-Za-z0-9_$]*))\s*:\s*"""
    r"""(?:"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)')"""
)


def parse_locale_block(source: str, const_name: str) -> dict[str, str]:
    match = re.search(rf"^const\s+{re.escape(const_name)}\s*=", source, re.M)
    if not match:
        return {}
    open_idx = source.find("{", match.end())
    if open_idx == -1:
        return {}
    block = js_block(source, open_idx)
    parsed: dict[str, str] = {}
    for key_quoted, key_single, key_bare, value_quoted, value_single in LOCALE_PAIR.findall(block):
        key = key_quoted or key_single or key_bare
        parsed[key] = value_quoted or value_single
    return parsed


WIRING_DEF = re.compile(r"^def ((?:register|install)_[a-z0-9_]+)\s*\(", re.M)


@check("ct_wiring", LAYER_CONTRACTS, "Registration functions are actually called")
def ct_wiring(ctx: Context):
    """A defined-but-never-called registration function is a whole feature, gone.

    Nothing about the code looks wrong: the module imports cleanly, the handlers
    are written, the route table is explicit. It is simply never invoked, so
    every endpoint it declares is missing at runtime and every caller 404s.
    """
    sources = walk(ctx.repo, (".py",), skip_dirs=("tests",))
    corpus = "\n".join(read_text(path) for path in sources)

    unwired: list[str] = []
    inspected = 0
    for path in sources:
        source = read_text(path)
        if "def register" not in source and "def install" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not re.match(r"^(?:register|install)_[a-z0-9_]+$", node.name):
                continue
            inspected += 1
            occurrences = len(re.findall(rf"\b{re.escape(node.name)}\s*\(", corpus))
            definitions = len(
                re.findall(rf"^def {re.escape(node.name)}\s*\(", corpus, re.M)
            )
            if occurrences - definitions > 0:
                continue
            body = ast.get_source_segment(source, node) or ""
            declared = sorted(set(re.findall(r"""["'](/minimax/[^"']*)["']""", body)))
            suffix = ""
            if declared:
                suffix = f" - declares {len(declared)} endpoint(s), e.g. {declared[0]}"
            unwired.append(f"{rel(path, ctx.repo)}:{node.lineno} {node.name}()" + suffix)

    ctx.metrics["registration_functions"] = inspected
    ctx.metrics["unwired_registration"] = unwired
    if unwired:
        ctx.add(
            Finding(
                ERROR,
                LAYER_CONTRACTS,
                "A registration function is never called",
                "Defined once, invoked nowhere. Whatever it registers does not "
                "exist at runtime, so every caller of it fails - and because the "
                "file itself is valid, nothing reports an error.",
                evidence=unwired,
                hint="Call it from the pack's startup path (__init__.py or the route registrar).",
            )
        )
        return STATUS_FAIL, f"{len(unwired)} of {inspected} unwired"
    return STATUS_PASS, f"{inspected} registration functions wired"


@check("i18n_parity", LAYER_I18N, "Locales define the same keys and placeholders")
def i18n_parity(ctx: Context):
    problems: list[str] = []
    totals: dict[str, int] = {}
    for relative, zh_name, en_name in I18N_MODULES:
        path = ctx.repo / relative
        if not path.is_file():
            continue
        source = read_text(path)
        zh = parse_locale_block(source, zh_name)
        en = parse_locale_block(source, en_name)
        totals[relative] = len(zh)
        missing_en = sorted(set(zh) - set(en))
        missing_zh = sorted(set(en) - set(zh))
        for key in missing_en[:10]:
            problems.append(f"{relative}: EN is missing {key!r} (falls back to the raw key)")
        for key in missing_zh[:10]:
            problems.append(f"{relative}: ZH is missing {key!r}")
        for key in sorted(set(zh) & set(en)):
            if len(PLACEHOLDER.findall(zh[key])) != len(PLACEHOLDER.findall(en[key])):
                problems.append(
                    f"{relative}: placeholder count differs for {key!r} -> "
                    f"ZH {len(PLACEHOLDER.findall(zh[key]))}, EN {len(PLACEHOLDER.findall(en[key]))}"
                )
    ctx.metrics["i18n_keys"] = totals
    if not totals:
        return STATUS_SKIP, "no locale blocks parsed"
    if problems:
        ctx.add(
            Finding(
                ERROR,
                LAYER_I18N,
                "Localization tables disagree",
                "A key present in one locale only renders as the raw dotted key "
                "for users of the other locale; a placeholder-count mismatch "
                "either drops information or prints a literal {token}.",
                evidence=problems[:25],
            )
        )
        return STATUS_FAIL, f"{len(problems)} mismatch(es)"
    return STATUS_PASS, ", ".join(f"{k.split('/')[-1]}={v}" for k, v in totals.items())


@check("i18n_keys", LAYER_I18N, "Translation keys used in code actually exist")
def i18n_keys(ctx: Context):
    known: set[str] = set()
    dict_spans: dict[str, list[tuple[int, int]]] = {}
    for relative, zh_name, en_name in I18N_MODULES:
        path = ctx.repo / relative
        if not path.is_file():
            continue
        source = read_text(path)
        known |= set(parse_locale_block(source, zh_name))
        known |= set(parse_locale_block(source, en_name))
        spans = []
        for const_name in (zh_name, en_name):
            match = re.search(rf"^const\s+{re.escape(const_name)}\s*=", source, re.M)
            if not match:
                continue
            open_idx = source.find("{", match.end())
            if open_idx == -1:
                continue
            spans.append((open_idx, open_idx + len(js_block(source, open_idx))))
        dict_spans[relative] = spans
    if not known:
        return STATUS_SKIP, "no keys parsed"

    # Only keys whose leading segment matches a known key family are treated as
    # candidate keys. Without that guard, every dotted string in the codebase
    # (log messages, CSS class names, URLs) would be reported as a missing key.
    families = {key.split(".")[0] for key in known}

    # A family guard alone is not enough: querySelector("button.cancel") is a CSS
    # selector, but "button" is a real key family in the material library, so the
    # selector would be reported as a missing translation. Restrict the scan to
    # identifiers that are actually locale lookups - every function the locale
    # modules export, which self-maintains as they gain accessors.
    accessors: set[str] = {"t", "tr", "mt", "mlT"}
    for relative, _zh, _en in I18N_MODULES:
        source = read_text(ctx.repo / relative)
        accessors |= set(re.findall(r"^export\s+function\s+([A-Za-z_$][A-Za-z0-9_$]*)", source, re.M))
    accessor_alt = "|".join(sorted(re.escape(name) for name in accessors))

    call_usage = re.compile(
        rf"""(?:^|[^A-Za-z0-9_$.])(?:{accessor_alt})\s*\(\s*["'`]([A-Za-z0-9_.]+)["'`]"""
    )
    qualified_usage = re.compile(
        rf"""\.(?:{accessor_alt})\s*\(\s*["'`]([A-Za-z0-9_.]+)["'`]"""
    )
    attribute = re.compile(
        r"""data-i18n(?:-title|-placeholder|-html)?\s*=\s*["']([A-Za-z0-9_.]+)["']"""
    )
    dynamic_call = re.compile(
        rf"""(?:^|[^A-Za-z0-9_$.])(?:{accessor_alt})\s*\(\s*["'`]([A-Za-z0-9_.]*\.)["'`]\s*[+`]"""
    )

    # Keys built by concatenation are only visible as a fragment. Both shapes
    # occur: t("a.b." + x) / t(`a.b.${x}`) and t("a.b" + map[k]) - the second has
    # no dot before the join, so it must not be mistaken for a real key.
    concat_fragment = re.compile(
        rf"""(?:^|[^A-Za-z0-9_$.])(?:{accessor_alt})\s*\(\s*["']([A-Za-z0-9_.]*)["']\s*\+"""
    )
    template_fragment = re.compile(
        rf"""(?:^|[^A-Za-z0-9_$.])(?:{accessor_alt})\s*\(\s*`([A-Za-z0-9_.]*)\$\{{"""
    )

    def accept(key: str) -> bool:
        return "." in key and not key.endswith(".") and key.split(".")[0] in families

    used: dict[str, list[str]] = {}
    fragments: set[str] = set()
    for path in frontend_files(ctx):
        source = read_text(path)
        for pattern in (call_usage, qualified_usage, attribute):
            for match in pattern.finditer(source):
                key = match.group(1)
                if not accept(key):
                    continue
                line = source.count("\n", 0, match.start()) + 1
                used.setdefault(key, []).append(f"{rel(path, ctx.repo)}:{line}")
        for pattern in (concat_fragment, template_fragment):
            for match in pattern.finditer(source):
                if match.group(1):
                    fragments.add(match.group(1))

    def composed(key: str) -> bool:
        """Built at runtime from a literal fragment this scan cannot resolve."""
        return any(key.startswith(fragment) for fragment in fragments)

    # "Unused" is judged by whether the key string appears as a token anywhere in
    # the frontend *outside* the locale dictionaries themselves. That counts
    # indirection tables (ASPECT_I18N_KEYS), attribute-driven lookups, and any
    # other channel a call-site scan would miss - while still excluding the
    # dictionary definition, which would otherwise make every key look used.
    token_re = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.]*")
    tokens: set[str] = set()
    for path in frontend_files(ctx):
        relative = rel(path, ctx.repo)
        source = read_text(path)
        for start, end in sorted(dict_spans.get(relative, []), reverse=True):
            source = source[:start] + source[end:]
        tokens |= set(token_re.findall(source))

    unknown = {
        key: where
        for key, where in used.items()
        if key not in known and not composed(key)
    }
    unused = sorted(
        key for key in known if key not in tokens and not composed(key)
    )
    ctx.metrics["i18n_unknown_keys"] = sorted(unknown)
    ctx.metrics["i18n_unused_keys"] = unused
    ctx.metrics["i18n_dynamic_prefixes"] = sorted(fragments)

    if unknown:
        ctx.add(
            Finding(
                WARNING,
                LAYER_I18N,
                "Code asks for translation keys that do not exist",
                "The lookup misses and the raw key is shown to the user.",
                evidence=[
                    f"{key}  (used at {where[0]})"
                    for key, where in sorted(unknown.items())[:25]
                ],
            )
        )
    if unused:
        ctx.add(
            Finding(
                INFO,
                LAYER_I18N,
                "Translation keys nothing appears to use",
                "The key string does not occur anywhere in the frontend outside "
                "the dictionary itself, so either the control that used it is "
                "gone, or the key was renamed and left behind.",
                evidence=unused[:25],
            )
        )
    if unknown:
        return STATUS_WARN, f"{len(unknown)} unknown, {len(unused)} unused"
    return STATUS_PASS, f"{len(known)} keys, {len(unused)} unused"


@check("i18n_coverage", LAYER_I18N, "User-visible text is translated", kind=KIND_ADVICE)
def i18n_coverage(ctx: Context):
    """How much UI text bypasses t() entirely."""
    assignment = re.compile(
        r"""\.(textContent|innerText|placeholder|title|label)\s*=\s*["']([A-Za-z][^"']{3,})["']"""
    )
    per_file: dict[str, int] = {}
    samples: list[str] = []
    for path in frontend_files(ctx):
        source = read_text(path)
        for match in assignment.finditer(source):
            text = match.group(2)
            if text.startswith("mmx") or "/" in text or text.endswith("()"):
                continue
            per_file[rel(path, ctx.repo)] = per_file.get(rel(path, ctx.repo), 0) + 1
            if len(samples) < 20:
                line = source.count("\n", 0, match.start()) + 1
                samples.append(f"{rel(path, ctx.repo)}:{line}  {match.group(1)} = {text[:60]!r}")

    total = sum(per_file.values())
    ctx.metrics["hardcoded_ui_strings"] = total
    if total:
        top = sorted(per_file.items(), key=lambda kv: -kv[1])[:8]
        ctx.add(
            Finding(
                SUGGESTION,
                LAYER_I18N,
                f"{total} user-visible string(s) bypass the translator",
                "Text assigned directly to a DOM property is English-only, even "
                "when the locale is Chinese. Grouped by file so the hot spots are "
                "obvious; this is a backlog item, not a defect.",
                evidence=[f"{count:>4}  {name}" for name, count in top] + samples[:8],
                hint="Route new strings through t() as you touch each area.",
            )
        )
        return STATUS_WARN, f"{total} strings"
    return STATUS_PASS, "all assigned text goes through t()"


# --------------------------------------------------------------------------- #
# Layer: flow / UX advice
# --------------------------------------------------------------------------- #


@check("fl_dead_inputs", LAYER_FLOW, "Every node input is read somewhere", kind=KIND_ADVICE)
def fl_dead_inputs(ctx: Context):
    """A declared input that no code ever mentions is a control that does nothing.

    This is the exact shape of the "I changed the setting and nothing happened"
    report, so it is worth surfacing even though the check is textual: a name can
    legitimately be handled through a generic loop, which is why this is advice
    rather than a defect.
    """
    classes = ctx.metrics.get("node_classes") or []
    if not classes:
        return STATUS_SKIP, "node classes not inspected"

    corpus_parts: list[str] = []
    for path in walk(ctx.repo / "director", (".py",)):
        corpus_parts.append(read_text(path))
    for path in walk(ctx.repo / "nodes", (".py",)):
        corpus_parts.append(read_text(path))
    for path in walk(ctx.repo / "patches", (".py",)):
        corpus_parts.append(read_text(path))
    for path in frontend_files(ctx):
        corpus_parts.append(read_text(path))
    corpus = "\n".join(corpus_parts)

    unread: list[str] = []
    inspected = 0
    for entry in classes:
        for name in entry.get("input_names", []) or []:
            inspected += 1
            if not re.search(rf"\b{re.escape(name)}\b", corpus):
                unread.append(f"{entry['class'].replace('MiniMaxH3MotionDirector', 'Director')}.{name}")

    ctx.metrics["inputs_inspected"] = inspected
    ctx.metrics["inputs_never_referenced"] = unread
    if unread:
        ctx.add(
            Finding(
                SUGGESTION,
                LAYER_FLOW,
                f"{len(unread)} node input(s) are never referenced in code",
                "A widget whose name appears nowhere in the backend or the "
                "frontend cannot affect anything. Some of these may be handled "
                "generically by a loop over the widget dict, so confirm before "
                "removing - but each one is a control a user can move with no "
                "effect.",
                evidence=unread[:25],
            )
        )
        return STATUS_WARN, f"{len(unread)} of {inspected}"
    return STATUS_PASS, f"{inspected} inputs referenced"


@check("fl_error_surfacing", LAYER_FLOW, "Failures reach the user", kind=KIND_ADVICE)
def fl_error_surfacing(ctx: Context):
    quiet: list[str] = []
    offenders: list[tuple[str, int]] = []
    for path in frontend_files(ctx):
        source = read_text(path)
        logged = len(re.findall(r"console\.(?:error|warn)\s*\(", source))
        if not logged:
            continue
        surfaces = bool(
            re.search(
                r"reportRunWarning|report_director_warning|noteRunWarning|showToast|showAlert|noticeList"
                r"|_runWarnings|pushWarning",
                source,
            )
        )
        if not surfaces:
            offenders.append((rel(path, ctx.repo), logged))
    for name, count in sorted(offenders, key=lambda kv: -kv[1]):
        quiet.append(f"{count:>4} console.error/warn   {name}")
    if quiet:
        ctx.add(
            Finding(
                SUGGESTION,
                LAYER_FLOW,
                "Modules log failures that the user never sees",
                "A console-only failure is invisible unless devtools are open, "
                "which is how a feature can appear to do nothing at all. Modules "
                "that also raise a run warning are excluded.",
                evidence=quiet[:20],
            )
        )
        return STATUS_WARN, f"{len(quiet)} module(s)"
    return STATUS_PASS, "every logging module also surfaces a warning"


@check("fl_maintainability", LAYER_FLOW, "Code hotspots worth knowing about", kind=KIND_ADVICE)
def fl_maintainability(ctx: Context):
    sized: list[tuple[int, str]] = []
    for path in walk(ctx.repo, (".py", ".js", ".mjs")):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix == ".py" and "tests" in path.parts:
            continue
        lines = len(read_text(path).splitlines())
        sized.append((lines, rel(path, ctx.repo)))
    sized.sort(reverse=True)

    long_functions: list[str] = []
    for path in walk(ctx.repo / "director", (".py",)):
        source = read_text(path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = (node.end_lineno or node.lineno) - node.lineno
                if length > 300:
                    long_functions.append(
                        f"{rel(path, ctx.repo)}:{node.lineno} {node.name}() {length} lines"
                    )

    todos = 0
    for path in walk(ctx.repo, (".py", ".js", ".mjs")):
        todos += len(re.findall(r"\b(?:TODO|FIXME|HACK|XXX)\b", read_text(path)))
    ctx.metrics["todos"] = todos
    ctx.metrics["largest_files"] = sized[:10]

    evidence = [f"{count:>6} lines  {name}" for count, name in sized[:8]]
    if long_functions:
        evidence += [f"long function: {entry}" for entry in long_functions[:8]]
    if todos:
        evidence.append(f"{todos} TODO/FIXME/HACK markers in the tree")
    ctx.add(
        Finding(
            INFO,
            LAYER_FLOW,
            "Maintainability snapshot",
            "Largest files and longest functions. The big frontend modules hold "
            "many independent features, so a change near the top has a large "
            "blast radius; new work is cheaper to add as a separate module.",
            evidence=evidence,
        )
    )
    return STATUS_PASS, f"largest {sized[0][0]} lines, {todos} markers"


# --------------------------------------------------------------------------- #
# Layer: live runtime
# --------------------------------------------------------------------------- #


def http_get(url: str, timeout: float = 20.0) -> tuple[int, str]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


@check("lv_reachable", LAYER_LIVE, "ComfyUI responds")
def lv_reachable(ctx: Context):
    if not ctx.args.live:
        return STATUS_SKIP, "pass --live to enable"
    status, body = http_get(f"{ctx.args.url.rstrip('/')}/system_stats", timeout=10)
    if status != 200:
        ctx.add(
            Finding(
                WARNING,
                LAYER_LIVE,
                "ComfyUI is not reachable",
                f"{ctx.args.url} returned status {status or 'error'}: {body[:200]}",
                hint="Start ComfyUI, or point --url at the right origin.",
            )
        )
        return STATUS_SKIP, "unreachable"
    try:
        stats = json.loads(body)
        ctx.metrics["comfy_system"] = {
            "devices": [d.get("name") for d in stats.get("devices", [])]
        }
    except Exception:  # noqa: BLE001
        pass
    return STATUS_PASS, ctx.args.url


@check("lv_nodes", LAYER_LIVE, "Registered node classes match the source")
def lv_nodes(ctx: Context):
    if not ctx.args.live:
        return STATUS_SKIP, "pass --live to enable"
    status, body = http_get(f"{ctx.args.url.rstrip('/')}/object_info", timeout=60)
    if status != 200:
        return STATUS_SKIP, f"/object_info status {status}"
    try:
        info = json.loads(body)
    except Exception:  # noqa: BLE001
        return STATUS_SKIP, "unparsable /object_info"

    expected = [
        "MiniMaxH3MotionDirector",
        "MiniMaxH3MotionDirectorInputs",
        "MiniMaxH3MotionDirectorAssets",
    ]
    absent = [name for name in expected if name not in info]
    ctx.metrics["live_node_inputs"] = {
        name: len(info.get(name, {}).get("input", {}).get("required", {}) or {})
        + len(info.get(name, {}).get("input", {}).get("optional", {}) or {})
        for name in expected
        if name in info
    }
    if absent:
        ctx.add(
            Finding(
                BLOCKER,
                LAYER_LIVE,
                "A node class is not registered in the running ComfyUI",
                "Either the pack failed to import at startup (check the console "
                "for a traceback) or ComfyUI is serving a different copy of the "
                "pack than the one being edited.",
                evidence=absent,
            )
        )
        return STATUS_FAIL, f"missing {', '.join(absent)}"
    return STATUS_PASS, ", ".join(
        f"{n.replace('MiniMaxH3MotionDirector', 'Director')}={v} inputs"
        for n, v in ctx.metrics["live_node_inputs"].items()
    )


@check("lv_modules_served", LAYER_LIVE, "Every frontend module is actually served")
def lv_modules_served(ctx: Context):
    """A 404 here is the 'panel never appears / retries forever' bug class.

    The browser has no way to report a missing ES module other than failing the
    whole import graph, so this is worth checking explicitly.
    """
    if not ctx.args.live:
        return STATUS_SKIP, "pass --live to enable"
    origin = ctx.args.url.rstrip("/")
    missing: list[str] = []
    checked = 0
    for path in frontend_files(ctx):
        name = path.name
        checked += 1
        status, _ = http_get(
            f"{origin}/extensions/{PLUGIN_DIR_NAME}/{name}", timeout=15
        )
        if status != 200:
            missing.append(f"{name} -> HTTP {status or 'error'}")
    ctx.metrics["live_modules_checked"] = checked
    if missing:
        ctx.add(
            Finding(
                ERROR,
                LAYER_LIVE,
                "Frontend module(s) are not served by ComfyUI",
                "The browser import graph fails at that module. If it is imported "
                "statically, everything downstream of it is dead too; if it is "
                "imported lazily, the feature silently never appears.",
                evidence=missing[:25],
            )
        )
        return STATUS_FAIL, f"{len(missing)} of {checked}"
    return STATUS_PASS, f"{checked} modules served"


@check("lv_get_routes", LAYER_LIVE, "GET routes answer without a server error")
def lv_get_routes(ctx: Context):
    if not ctx.args.live:
        return STATUS_SKIP, "pass --live to enable"
    routes = ctx.metrics.get("routes") or []
    origin = ctx.args.url.rstrip("/")
    gets = [path for method, path in routes if method == "GET" and "{" not in path]
    if not gets:
        return STATUS_SKIP, "no parameterless GET routes known"
    broken: list[str] = []
    reached: list[str] = []
    for path in gets:
        status, body = http_get(f"{origin}{path}", timeout=30)
        if status == 0 or status >= 500:
            broken.append(f"{path} -> HTTP {status or 'error'} {body[:120]}")
        else:
            reached.append(f"{path} -> {status}")
    if broken:
        ctx.add(
            Finding(
                ERROR,
                LAYER_LIVE,
                "GET route(s) raise a server error",
                "A 5xx here means the handler threw before it could validate "
                "input, which usually points at a missing dependency or an "
                "uninitialised service.",
                evidence=broken[:15],
            )
        )
        return STATUS_FAIL, f"{len(broken)} of {len(gets)}"
    return STATUS_PASS, f"{len(gets)} routes answered ({', '.join(reached[:4])})"


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def selected_checks(args) -> list[Check]:
    wanted = [layer for layer in (args.only or "").split(",") if layer.strip()] if args.only else []
    chosen: list[Check] = []
    for item in CHECKS:
        if item.layer == LAYER_LIVE and not args.live:
            continue
        if wanted and item.layer not in wanted:
            continue
        if args.no_advice and item.kind == KIND_ADVICE:
            continue
        if args.fast and item.layer == LAYER_SUITES:
            continue
        chosen.append(item)
    return chosen


def run_checks(ctx: Context, checks: list[Check]) -> None:
    for item in checks:
        label = f"{item.layer}/{item.cid}"
        print(f"  ... {item.title}", flush=True)
        started = time.time()
        try:
            status, note = item.fn(ctx)
        except Exception as exc:  # noqa: BLE001 - one broken check must not end the sweep
            ctx.check_status[item.cid] = STATUS_FAIL
            ctx.check_note[item.cid] = f"{type(exc).__name__}: {exc}"
            ctx.add(
                Finding(
                    WARNING,
                    item.layer,
                    f"Check crashed: {item.title}",
                    f"{type(exc).__name__}: {exc}",
                    hint="A crash in a check is a bug in the check, not necessarily in the pack.",
                )
            )
            print(f"      crashed ({time.time() - started:.1f}s)", flush=True)
            continue
        ctx.check_status[item.cid] = status
        ctx.check_note[item.cid] = note or ""
        icon = {
            STATUS_PASS: "ok  ",
            STATUS_WARN: "warn",
            STATUS_FAIL: "FAIL",
            STATUS_SKIP: "skip",
        }.get(status, "?   ")
        print(f"      [{icon}] {note}  ({time.time() - started:.1f}s)", flush=True)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def matrix(ctx: Context, checks: list[Check]) -> dict[str, dict]:
    """Per-layer readiness rollup.

    A layer is BROKEN if any check in it failed, PARTIAL if anything warned (or
    was skipped for a reason that hides coverage), READY otherwise.
    """
    result: dict[str, dict] = {}
    for layer_id, layer_label in LAYERS:
        members = [c for c in checks if c.layer == layer_id]
        if not members:
            continue
        statuses = [ctx.check_status.get(c.cid, STATUS_SKIP) for c in members]
        if STATUS_FAIL in statuses:
            verdict = "BROKEN"
        elif STATUS_WARN in statuses:
            verdict = "PARTIAL"
        elif all(s == STATUS_SKIP for s in statuses):
            verdict = "NOT RUN"
        else:
            verdict = "READY"
        result[layer_id] = {
            "label": layer_label,
            "verdict": verdict,
            "checks": len(members),
            "failed": sum(1 for s in statuses if s == STATUS_FAIL),
            "warned": sum(1 for s in statuses if s == STATUS_WARN),
            "skipped": sum(1 for s in statuses if s == STATUS_SKIP),
        }
    return result


def build_report(ctx: Context, checks: list[Check]) -> dict:
    ordered = sorted(
        ctx.findings, key=lambda f: (SEVERITY_RANK[f.severity], f.layer, f.title)
    )
    counts = {name: 0 for name in SEVERITY_ORDER}
    for finding in ctx.findings:
        counts[finding.severity] += 1
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round(time.time() - ctx.started, 1),
        "repo": str(ctx.repo),
        "install": str(ctx.install) if ctx.install else None,
        "comfy_root": str(ctx.comfy_root) if ctx.comfy_root else None,
        "live_url": ctx.args.url if ctx.args.live else None,
        "verdict": verdict_for(ctx, counts),
        "counts": counts,
        "matrix": matrix(ctx, checks),
        "metrics": ctx.metrics,
        "findings": [f.to_dict() for f in ordered],
        "checks": [
            {
                "id": c.cid,
                "layer": c.layer,
                "title": c.title,
                "kind": c.kind,
                "status": ctx.check_status.get(c.cid, STATUS_SKIP),
                "note": ctx.check_note.get(c.cid, ""),
            }
            for c in checks
        ],
        "notes": ctx.notes,
    }


def verdict_for(ctx: Context, counts: dict) -> str:
    if counts[BLOCKER]:
        return "NOT READY"
    if counts[ERROR]:
        return "NEEDS WORK"
    if counts[WARNING]:
        return "READY WITH CAVEATS"
    return "READY"


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append("# QA readiness sweep")
    lines.append("")
    lines.append(f"**Verdict: {report['verdict']}**  ")
    lines.append(
        f"_{report['generated']} · {report['duration_seconds']}s · "
        f"{report['counts'][BLOCKER]} blocker, {report['counts'][ERROR]} error, "
        f"{report['counts'][WARNING]} warning, {report['counts'][SUGGESTION]} suggestion_"
    )
    lines.append("")
    lines.append(f"- Repo: `{report['repo']}`")
    if report.get("install"):
        lines.append(f"- Install copy: `{report['install']}`")
    if report.get("comfy_root"):
        lines.append(f"- ComfyUI: `{report['comfy_root']}`")
    if report.get("live_url"):
        lines.append(f"- Live instance: {report['live_url']}")
    lines.append("")

    lines.append("## Readiness by area")
    lines.append("")
    lines.append("| Area | Verdict | Checks | Failed | Warned | Skipped |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
    for layer_id, entry in report["matrix"].items():
        lines.append(
            f"| {entry['label']} | {entry['verdict']} | {entry['checks']} | "
            f"{entry['failed']} | {entry['warned']} | {entry['skipped']} |"
        )
    lines.append("")

    if report["findings"]:
        lines.append("## Findings")
        lines.append("")
        for finding in report["findings"]:
            lines.append(f"### `{finding['severity']}` {finding['title']}")
            lines.append("")
            if finding["detail"]:
                lines.append(finding["detail"])
                lines.append("")
            if finding["evidence"]:
                lines.append("```")
                lines.extend(finding["evidence"])
                lines.append("```")
                lines.append("")
            if finding["hint"]:
                lines.append(f"**Next step:** {finding['hint']}")
                lines.append("")
    else:
        lines.append("## Findings")
        lines.append("")
        lines.append("None. Every check passed.")
        lines.append("")

    lines.append("## Check inventory")
    lines.append("")
    lines.append("| Area | Check | Status | Detail |")
    lines.append("| --- | --- | --- | --- |")
    for entry in report["checks"]:
        note = (entry["note"] or "").replace("|", "\\|")[:160]
        lines.append(
            f"| {entry['layer']} | {entry['title']} | {entry['status']} | {note} |"
        )
    lines.append("")

    if report["notes"]:
        lines.append("## Notes")
        lines.append("")
        for note in report["notes"]:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)


def print_summary(report: dict) -> None:
    width = 68
    print()
    print("=" * width)
    print(f"  QA READINESS: {report['verdict']}")
    print("=" * width)
    for entry in report["matrix"].values():
        print(f"  {entry['label']:<26} {entry['verdict']}")
    print("-" * width)
    counts = report["counts"]
    print(
        f"  {counts[BLOCKER]} blocker · {counts[ERROR]} error · "
        f"{counts[WARNING]} warning · {counts[SUGGESTION]} suggestion"
        f"   ({report['duration_seconds']}s)"
    )
    print("-" * width)
    for finding in report["findings"]:
        if finding["severity"] in (BLOCKER, ERROR):
            print(f"  [{finding['severity']}] {finding['title']}")
            if finding["evidence"]:
                print(f"        {finding['evidence'][0]}")
    shown = [f for f in report["findings"] if f["severity"] not in (BLOCKER, ERROR)]
    if shown:
        print()
        for finding in shown[:6]:
            print(f"  [{finding['severity']}] {finding['title']}")
    print("=" * width)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def find_install_copy(repo: Path) -> Path | None:
    env = os.environ.get("MMX_DIRECTOR_INSTALL")
    if env and Path(env).is_dir():
        return Path(env)
    candidates = [
        Path("/mnt/ssd2/cmfy/ComfyUI-Easy-Install/ComfyUI/custom_nodes") / PLUGIN_DIR_NAME,
        Path.home() / "ComfyUI" / "custom_nodes" / PLUGIN_DIR_NAME,
        Path("/opt/ComfyUI/custom_nodes") / PLUGIN_DIR_NAME,
    ]
    # Also look for a sibling checkout, e.g. .../ComfyUI/custom_nodes/<pack>
    parent = repo.parent
    if parent.name == "custom_nodes":
        return repo
    for candidate in candidates:
        if candidate.is_dir() and candidate.resolve() != repo.resolve():
            return candidate
    return None


def find_comfy_root(repo: Path, explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("COMFY_ROOT")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    parent = repo.parent
    if parent.name == "custom_nodes" and (parent.parent / "folder_paths.py").is_file():
        return parent.parent
    for candidate in (
        Path("/mnt/ssd2/cmfy/ComfyUI-Easy-Install/ComfyUI"),
        Path.home() / "ComfyUI",
        Path("/opt/ComfyUI"),
    ):
        if (candidate / "folder_paths.py").is_file():
            return candidate.resolve()
    return None


def default_python() -> str:
    env = os.environ.get("MMX_DIRECTOR_PYTHON")
    if env and Path(env).exists():
        return env
    embedded = Path(
        "/mnt/ssd2/cmfy/ComfyUI-Easy-Install/python_embeded/bin/python3"
    )
    if embedded.exists():
        return str(embedded)
    return sys.executable


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="qa_readiness.py",
        description="QA readiness sweep for the MiniMax H3 Motion Director pack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "layers: toolchain, backend, frontend, suites, contracts, i18n, flow, live\n"
            "examples:\n"
            "  qa_readiness.py --fast                 static sweep only\n"
            "  qa_readiness.py --live                 include a running ComfyUI\n"
            "  qa_readiness.py --only contracts,i18n  focus on specific layers\n"
        ),
    )
    parser.add_argument("--repo", default=None, help="pack checkout (default: this script's repo)")
    parser.add_argument("--install", default=None, help="ComfyUI install copy, for drift detection")
    parser.add_argument("--comfy-root", default=None, help="ComfyUI checkout root")
    parser.add_argument("--python", default=None, help="interpreter that runs ComfyUI")
    parser.add_argument("--node", default="node", help="node binary for frontend checks")
    parser.add_argument("--only", default="", help="comma-separated layer ids to run")
    parser.add_argument("--fast", action="store_true", help="skip the test suites")
    parser.add_argument("--no-advice", action="store_true", help="skip heuristic/advice checks")
    parser.add_argument("--live", action="store_true", help="probe a running ComfyUI")
    parser.add_argument("--url", default="http://127.0.0.1:8188", help="ComfyUI origin for --live")
    parser.add_argument("--suite-timeout", type=int, default=1800, help="seconds per suite")
    parser.add_argument(
        "--fail-on",
        default="error",
        choices=["blocker", "error", "warning", "never"],
        help="severity that makes the exit code non-zero (default: error)",
    )
    parser.add_argument("--out", default="artifacts", help="report output directory")
    parser.add_argument("--no-report", action="store_true", help="print only, write nothing")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo = (
        Path(args.repo).expanduser().resolve()
        if args.repo
        else Path(__file__).resolve().parent.parent
    )
    if not (repo / "web" / "js").is_dir():
        print(f"error: {repo} does not look like the pack checkout", file=sys.stderr)
        return 2

    ctx = Context(
        repo=repo,
        install=Path(args.install).expanduser().resolve() if args.install else find_install_copy(repo),
        comfy_root=find_comfy_root(repo, args.comfy_root),
        python=args.python or default_python(),
        node=args.node,
        args=args,
    )

    checks = selected_checks(args)
    if not checks:
        print("error: no checks selected", file=sys.stderr)
        return 2

    print()
    print(f"QA readiness sweep - {repo}")
    print(
        f"  python={ctx.python}  install={ctx.install or '(none)'}  "
        f"comfy={ctx.comfy_root or '(none)'}"
    )
    print(f"  {len(checks)} checks")
    print()

    run_checks(ctx, checks)
    report = build_report(ctx, checks)

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = repo / out_dir
    if not args.no_report:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "qa_readiness_report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            (out_dir / "qa_readiness_report.md").write_text(
                render_markdown(report), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  warning: could not write reports: {exc}", file=sys.stderr)

    print_summary(report)
    if not args.no_report:
        print(f"  reports: {out_dir / 'qa_readiness_report.md'}")
        print()

    threshold = {
        "blocker": [BLOCKER],
        "error": [BLOCKER, ERROR],
        "warning": [BLOCKER, ERROR, WARNING],
        "never": [],
    }[args.fail_on]
    if any(report["counts"][severity] for severity in threshold):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
