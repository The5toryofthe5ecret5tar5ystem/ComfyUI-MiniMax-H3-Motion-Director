const SECTION_DEFS = Object.freeze([
    {
        kind: "picture",
        field: "refs",
        max: 9,
        hasMedia: (item) => !!item?.imageFile,
    },
    {
        kind: "video",
        field: "refVideos",
        max: 3,
        hasMedia: (item) => !!(item?.videoFile || item?.fileName || item?.previewImageFile || item?.previewImageUrl),
    },
    {
        kind: "audio",
        field: "refAudios",
        max: 3,
        hasMedia: (item) => !!(item?.audioFile || item?.fileName),
    },
]);

function itemSlot(item) {
    const slot = Number(item?.index ?? item?.slot);
    return Number.isInteger(slot) && slot >= 0 ? slot : -1;
}

export function firstFreeReferenceSlot(items, maxSlots) {
    const occupied = new Set((items || []).map(itemSlot).filter((slot) => slot >= 0));
    for (let slot = 0; slot < Math.max(0, Number(maxSlots) || 0); slot += 1) {
        if (!occupied.has(slot)) return slot;
    }
    return null;
}

export function buildR2vCommonSections(common = {}) {
    return SECTION_DEFS.map((definition) => {
        const source = Array.isArray(common?.[definition.field]) ? common[definition.field] : [];
        const items = source
            .filter((item) => definition.hasMedia(item))
            .map((item) => ({ ...item, slot: itemSlot(item) }))
            .filter((item) => item.slot >= 0 && item.slot < definition.max)
            .sort((left, right) => left.slot - right.slot);
        return {
            ...definition,
            items,
            addSlot: firstFreeReferenceSlot(items, definition.max),
        };
    });
}

export function renderR2vCommonSections(container, sections, {
    documentRef = globalThis.document,
    labels = {},
    renderAsset,
    onAdd,
} = {}) {
    if (!container?.replaceChildren || !documentRef?.createElement) return;
    container.replaceChildren();
    for (const section of sections || []) {
        const sectionElement = documentRef.createElement("section");
        sectionElement.className = "bd-r2v-common-popover-section";
        sectionElement.setAttribute("data-kind", section.kind);

        const heading = documentRef.createElement("div");
        heading.className = "bd-r2v-common-popover-section-head";
        const title = documentRef.createElement("b");
        title.textContent = String(labels.section?.(section.kind) || section.kind);
        const count = documentRef.createElement("span");
        count.textContent = String(section.items.length) + "/" + String(section.max);
        heading.append(title, count);
        sectionElement.appendChild(heading);

        const grid = documentRef.createElement("div");
        grid.className = "bd-r2v-common-popover-grid";
        for (const item of section.items) {
            const card = documentRef.createElement("div");
            card.className = "bd-r2v-common-popover-asset";
            card.setAttribute("data-kind", section.kind);
            card.setAttribute("data-slot", String(item.slot));
            renderAsset?.(section, item, card);
            grid.appendChild(card);
        }
        if (section.addSlot !== null) {
            const add = documentRef.createElement("button");
            add.type = "button";
            add.className = "bd-r2v-common-popover-add";
            add.setAttribute("data-kind", section.kind);
            add.setAttribute("data-slot", String(section.addSlot));
            add.textContent = String(labels.add?.(section.kind) || "+");
            add.onclick = (event) => {
                event.preventDefault?.();
                event.stopPropagation?.();
                onAdd?.(section, section.addSlot);
            };
            grid.appendChild(add);
        }
        sectionElement.appendChild(grid);
        container.appendChild(sectionElement);
    }
}

export function computePopoverPosition(anchorRect, panelRect, viewport = {}) {
    const viewportWidth = Math.max(1, Number(viewport.width) || 1);
    const viewportHeight = Math.max(1, Number(viewport.height) || 1);
    const margin = 8;
    const gap = 8;
    const width = Math.min(760, Math.max(1, viewportWidth - 32));
    const maxHeight = Math.min(720, Math.max(1, viewportHeight * 0.7));
    const panelHeight = Math.min(Math.max(1, Number(panelRect?.height) || maxHeight), maxHeight);
    const left = Math.min(
        Math.max(margin, Number(anchorRect?.left) || margin),
        Math.max(margin, viewportWidth - width - margin),
    );
    const belowTop = (Number(anchorRect?.bottom) || margin) + gap;
    const aboveTop = (Number(anchorRect?.top) || margin) - gap - panelHeight;
    const spaceBelow = viewportHeight - belowTop - margin;
    const spaceAbove = (Number(anchorRect?.top) || margin) - gap - margin;
    const preferredTop = spaceBelow >= panelHeight || spaceBelow >= spaceAbove
        ? belowTop
        : aboveTop;
    const top = Math.min(
        Math.max(margin, preferredTop),
        Math.max(margin, viewportHeight - panelHeight - margin),
    );
    return { left, top, width, maxHeight };
}

export function createR2vCommonPopover({
    anchor,
    overlayLayer,
    documentRef = globalThis.document,
    windowRef = globalThis.window,
    onOpenChange,
    onRender,
} = {}) {
    if (!anchor?.contains || !overlayLayer?.appendChild || !documentRef?.createElement) {
        throw new Error("R2V Common popover requires an anchor and Director overlay layer.");
    }

    const panel = documentRef.createElement("aside");
    panel.className = "bd-r2v-common-popover";
    panel.setAttribute("data-r", "r2v-common-popover");
    panel.setAttribute("role", "dialog");
    panel.hidden = true;
    const title = documentRef.createElement("div");
    title.className = "bd-r2v-common-popover-title";
    const titleText = documentRef.createElement("span");
    titleText.className = "bd-r2v-common-popover-title-text";
    const titleHint = documentRef.createElement("span");
    titleHint.className = "bd-r2v-common-popover-title-hint";
    titleHint.hidden = true;
    title.append(titleText, titleHint);
    const body = documentRef.createElement("div");
    body.className = "bd-r2v-common-popover-body bd-batch-r2v";
    panel.append(title, body);
    overlayLayer.appendChild(panel);

    let open = false;
    const position = () => {
        if (!open) return;
        const layout = computePopoverPosition(
            anchor.getBoundingClientRect(),
            panel.getBoundingClientRect(),
            { width: windowRef.innerWidth, height: windowRef.innerHeight },
        );
        panel.style.left = String(layout.left) + "px";
        panel.style.top = String(layout.top) + "px";
        panel.style.width = String(layout.width) + "px";
        panel.style.maxHeight = String(layout.maxHeight) + "px";
    };
    const notify = () => onOpenChange?.(open);
    const manager = {
        panel,
        title,
        body,
        get isOpen() { return open; },
        setTitle(value) {
            titleText.textContent = String(value || "");
            panel.setAttribute("aria-label", titleText.textContent);
        },
        setHint(value) {
            titleHint.textContent = String(value || "");
            titleHint.hidden = !value;
        },
        render() {
            onRender?.(body);
            if (open) windowRef.requestAnimationFrame?.(position);
        },
        open() {
            if (open) return;
            open = true;
            panel.hidden = false;
            panel.classList.add("open");
            manager.render();
            position();
            notify();
        },
        close() {
            if (!open) return;
            open = false;
            panel.hidden = true;
            panel.classList.toggle("open", false);
            notify();
        },
        toggle() {
            if (open) manager.close();
            else manager.open();
        },
        position,
        destroy() {
            manager.close();
            documentRef.removeEventListener?.("pointerdown", onPointerDown, true);
            windowRef.removeEventListener?.("keydown", onKeyDown, true);
            windowRef.removeEventListener?.("resize", position);
            panel.remove();
        },
    };

    const onPointerDown = (event) => {
        if (!open || panel.contains(event.target) || anchor.contains(event.target)) return;
        manager.close();
    };
    const onKeyDown = (event) => {
        if (!open || event.key !== "Escape") return;
        event.preventDefault?.();
        event.stopPropagation?.();
        manager.close();
    };
    documentRef.addEventListener?.("pointerdown", onPointerDown, true);
    windowRef.addEventListener?.("keydown", onKeyDown, true);
    windowRef.addEventListener?.("resize", position);
    return manager;
}
