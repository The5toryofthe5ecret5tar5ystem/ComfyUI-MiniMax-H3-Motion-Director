// Prompt-enhancer batch run: rewrite every segment prompt, then let the user
// accept or reject each result before anything is applied.
//
// Why a review step rather than writing straight through: at roughly 40 s per
// prompt on a 17B-class local model, a 27-segment project is a ~15 minute job
// whose output lands in prose the user wrote by hand. Applying it blind would
// mean 27 silent overwrites to audit afterwards; applying nothing until the user
// has seen it means the worst case is one rejected row.
//
// Deliberately self-contained: it reaches the editor only through the enhancer
// panel's public API (getPromptBlock / getPromptTextForBlock / setPromptTextFor
// Block / callEnhanceApi), so it needs no changes inside minimax_timeline.js.

let activeRun = null;

/** Seconds per prompt, measured on a 3B GGUF at 16k context with H3 loaded. */
const SECONDS_PER_PROMPT = 40;

function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    Object.assign(node.style, props);
    for (const child of children) {
        node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
}

function button(label, props, onClick) {
    const node = el("button", {
        padding: "6px 12px",
        fontSize: "11px",
        fontWeight: "600",
        borderRadius: "6px",
        border: "1px solid #2a3140",
        background: "#252a34",
        color: "#e8ecf4",
        cursor: "pointer",
        ...props,
    }, [label]);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
}

function truncate(text, limit) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length > limit ? `${clean.slice(0, limit)}…` : clean;
}

/** Builds the review overlay. Returns the overlay element plus its handles. */
function buildOverlay(editor, rows) {
    const overlay = el("div", {
        position: "fixed",
        inset: "0",
        zIndex: "13000",
        background: "rgba(8,10,14,.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
    });
    const card = el("div", {
        width: "min(920px, 94vw)",
        maxHeight: "86vh",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        background: "#161a22",
        border: "1px solid #2a3140",
        borderRadius: "12px",
        padding: "16px",
        color: "#e8ecf4",
        fontFamily: "system-ui, sans-serif",
    });

    const title = el("div", { fontSize: "13px", fontWeight: "700" }, ["Prompt enhancement results"]);
    const sub = el("div", { fontSize: "11px", opacity: ".75" }, [
        "Untick anything you do not want. Nothing is applied until you press Apply.",
    ]);
    card.append(title, sub);

    const list = el("div", {
        display: "flex",
        flexDirection: "column",
        gap: "8px",
        overflow: "auto",
        flex: "1 1 auto",
    });

    const checkboxes = [];
    for (const row of rows) {
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = true;
        checkboxes.push(box);

        const body = el("div", { display: "flex", flexDirection: "column", gap: "4px", minWidth: "0" });
        body.append(
            el("div", { fontSize: "10px", opacity: ".65" }, [`Segment ${row.segmentIndex + 1}`]),
            el("div", { fontSize: "11px", opacity: ".8", lineHeight: "1.45" }, [truncate(row.original, 220)]),
            el("div", { fontSize: "11px", lineHeight: "1.45", color: "#c7d2fe" }, [truncate(row.enhanced, 700)]),
        );

        const item = el("label", {
            display: "flex",
            gap: "10px",
            alignItems: "flex-start",
            background: "#1b2029",
            border: "1px solid #232a36",
            borderRadius: "8px",
            padding: "10px",
            cursor: "pointer",
        }, [box, body]);
        list.appendChild(item);
    }
    card.appendChild(list);

    const footer = el("div", { display: "flex", gap: "8px", justifyContent: "flex-end" });
    const applyBtn = button("Apply selected", { background: "#6366f1", borderColor: "#6366f1" }, () => {
        const chosen = rows.filter((_row, index) => checkboxes[index].checked);
        // One commit for the whole batch: a single undo entry covering the run,
        // rather than 27 steps the user has to unwind individually.
        for (const row of chosen) pe.setPromptTextForBlock(row.enhanced, row.segmentIndex);
        editor.commit?.(false, { syncTimeline: true });
        close(`${chosen.length} segment prompt(s) updated`);
    });
    const cancelBtn = button("Cancel", {}, () => close("Batch cancelled; nothing applied"));
    footer.append(cancelBtn, applyBtn);
    card.appendChild(footer);

    overlay.appendChild(card);

    function close(message) {
        overlay.remove();
        if (activeRun) activeRun.done = true;
        if (message) pe.setStatus(message, "success");
    }

    return { overlay, close };
}

/** Builds the progress overlay shown while the batch is running. */
function buildProgress(editor, total) {
    const overlay = el("div", {
        position: "fixed",
        inset: "0",
        zIndex: "13000",
        background: "rgba(8,10,14,.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
    });
    const card = el("div", {
        minWidth: "320px",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        background: "#161a22",
        border: "1px solid #2a3140",
        borderRadius: "12px",
        padding: "18px",
        color: "#e8ecf4",
        fontFamily: "system-ui, sans-serif",
    });
    const label = el("div", { fontSize: "12px", fontWeight: "600" }, [`Enhancing 0 / ${total}…`]);
    const bar = el("div", { height: "6px", background: "#252a34", borderRadius: "3px", overflow: "hidden" });
    const fill = el("div", { height: "100%", width: "0%", background: "#6366f1", transition: "width .2s" });
    bar.appendChild(fill);
    const hint = el("div", { fontSize: "10px", opacity: ".7" }, [
        "Local generation runs one prompt at a time. You can stop after the current one.",
    ]);
    const stop = button("Stop", { alignSelf: "flex-end" }, () => {
        if (activeRun) activeRun.stopped = true;
        label.textContent = "Stopping after the current prompt…";
    });
    card.append(label, bar, hint, stop);
    overlay.appendChild(card);
    return {
        overlay,
        setProgress(done, totalCount) {
            label.textContent = `Enhancing ${done} / ${totalCount}…`;
            fill.style.width = `${totalCount ? Math.round((done / totalCount) * 100) : 0}%`;
        },
        close() { overlay.remove(); },
    };
}

/**
 * Run enhancement across every segment that has a prompt.
 *
 * Text-only by design: reference-image collection is per-block and comparatively
 * slow, so a batch run of 27 segments would spend its time re-extracting frames.
 * Single-prompt enhancement still uses the full vision path.
 */
export async function runPromptEnhanceBatch(editor, pe) {
    if (activeRun && !activeRun.done) {
        pe.setStatus("A batch is already running.", "info");
        return;
    }
    const segments = editor.timeline?.segments || [];
    const targets = [];
    for (let index = 0; index < segments.length; index += 1) {
        if (pe.getPromptTextForBlock(index)) targets.push(index);
    }
    if (!targets.length) {
        pe.setStatus("No segment prompts to enhance.", "error");
        return;
    }

    const cfg = pe.getLlmConfig();
    if (!cfg.model) {
        pe.setStatus("Choose a model in the enhancer settings first.", "error");
        return;
    }

    const minutes = Math.max(1, Math.round((targets.length * SECONDS_PER_PROMPT) / 60));
    const go = window.confirm(
        `Enhance ${targets.length} segment prompt(s)?\n\n`
        + `This runs your local model once per prompt, about ${SECONDS_PER_PROMPT}s each `
        + `- roughly ${minutes} minute(s).\n\n`
        + "You will see every result before anything is applied.",
    );
    if (!go) return;

    const run = { done: false, stopped: false };
    activeRun = run;
    const progress = buildProgress(editor, targets.length);
    editor.root?.appendChild(progress.overlay);

    const rows = [];
    try {
        for (let position = 0; position < targets.length; position += 1) {
            if (run.stopped) break;
            const segmentIndex = targets[position];
            const prompt = pe.getPromptTextForBlock(segmentIndex);
            const { block, taskKey } = pe.getPromptBlock(segmentIndex);
            progress.setProgress(position, targets.length);
            try {
                const result = await pe.callEnhanceApi(prompt, taskKey, block, {
                    ...cfg,
                    // Batch is text-only: skip the per-block image gathering.
                    skipVision: true,
                });
                if (result?.ok && result.text) {
                    rows.push({ segmentIndex, original: prompt, enhanced: result.text });
                }
            } catch (error) {
                console.warn(`[MiniMax H3 PE] segment ${segmentIndex + 1} failed:`, error);
            }
        }
    } finally {
        progress.close();
        run.done = true;
    }

    if (!rows.length) {
        pe.setStatus("No prompts were enhanced (all attempts failed).", "error");
        return;
    }

    const { overlay } = buildOverlay(editor, rows);
    const stopNote = run.stopped ? " (stopped early)" : "";
    editor.root?.appendChild(overlay);
    pe.setStatus(`Enhanced ${rows.length} prompt(s)${stopNote} - review the list`, "success");
    return true;
}
