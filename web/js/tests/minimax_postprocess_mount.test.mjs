import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// The module touches `document` when it mounts, so the DOM has to exist before
// it is imported.  Static imports hoist, hence the dynamic import below.
const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;

const ui = await import("../minimax_postprocess_ui.mjs");

const change = (element) => element.dispatchEvent(new dom.window.Event("change", { bubbles: true }));

function mount(config = {}) {
    const widget = { value: JSON.stringify(config), callback: null };
    const store = new ui.PostprocessConfigStore(widget);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const view = ui.mountPostprocessUI(host, store, { locale: () => "en", directorSize: () => [864, 480] });
    return { host, store, view, widget };
}

// --------------------------------------------------------------------------
// The panel renders three columns, not two.
// --------------------------------------------------------------------------
{
    const { host } = mount({});
    const sections = [...host.querySelectorAll("[data-section]")].map((el) => el.dataset.section);
    assert.deepEqual(sections, ["global_refine", "face_refine", "audio_refine"]);
    assert.equal(host.querySelectorAll('[data-summary="audio_refine"]').length, 1);
}

// --------------------------------------------------------------------------
// Room dropdown carries every preset the Python side knows about.
// --------------------------------------------------------------------------
{
    const { host } = mount({});
    const select = host.querySelector('[data-path="audio_refine.room"]');
    assert.ok(select, "room select must exist");
    const values = [...select.options].map((option) => option.value);
    assert.deepEqual(values, ["", ...ui.ROOM_NAMES], "dropdown must offer Custom plus every preset");
}

// --------------------------------------------------------------------------
// A named room hides the six manual values, because the preset supplies them.
// --------------------------------------------------------------------------
{
    const { host, store } = mount({ audio_refine: { enabled: true, room: "bathroom" } });
    const reverbField = host.querySelector('[data-path="audio_refine.reverberance"]');
    const wrap = reverbField.closest("[data-conditional]");
    assert.equal(wrap.hidden, true, "preset selection must hide the manual values");

    assert.equal(store.get().audio_refine.room, "bathroom");
    assert.equal(host.querySelector('[data-path="audio_refine.room"]').value, "bathroom");
    assert.match(host.querySelector('[data-summary="audio_refine"]').textContent, /Bathroom/);
}

// --------------------------------------------------------------------------
// Choosing Custom reveals them and writes through to the store.
// --------------------------------------------------------------------------
{
    const { host, store, widget } = mount({ audio_refine: { enabled: true, room: "bathroom" } });
    const select = host.querySelector('[data-path="audio_refine.room"]');
    select.value = "";
    change(select);

    assert.equal(store.get().audio_refine.room, "");
    assert.equal(host.querySelector('[data-path="audio_refine.reverberance"]').closest("[data-conditional]").hidden, false);
    assert.match(host.querySelector('[data-summary="audio_refine"]').textContent, /Custom room/);
    assert.ok(widget.value.includes('"audio_refine"'), "store must persist back to the widget");
}

// --------------------------------------------------------------------------
// Numeric edits round-trip and are clamped.
// --------------------------------------------------------------------------
{
    const { host, store } = mount({ audio_refine: { enabled: true, room: "" } });
    const gain = host.querySelector('[data-path="audio_refine.gain_db"]');
    gain.value = "-6";
    change(gain);
    assert.equal(store.get().audio_refine.gain_db, -6);

    // An emptied number field falls back to the default instead of becoming 0.
    const reverb = host.querySelector('[data-path="audio_refine.reverberance"]');
    reverb.value = "";
    change(reverb);
    assert.equal(store.get().audio_refine.reverberance, 40);
}

// --------------------------------------------------------------------------
// The enable checkbox drives the dimmed state, like the other two sections.
// --------------------------------------------------------------------------
{
    const { host, store } = mount({ audio_refine: { enabled: true, room: "hall" } });
    const enable = host.querySelector('[data-path="audio_refine.enabled"]');
    assert.equal(enable.checked, true);
    assert.equal(host.querySelector('[data-section="audio_refine"]').classList.contains("mmx-post-disabled"), false);

    enable.checked = false;
    change(enable);
    assert.equal(store.get().audio_refine.enabled, false);
    assert.equal(host.querySelector('[data-section="audio_refine"]').classList.contains("mmx-post-disabled"), true);
}

// --------------------------------------------------------------------------
// Per-segment flips which explanatory note is shown.
// --------------------------------------------------------------------------
{
    const { host, store } = mount({ audio_refine: { enabled: true, room: "hall" } });
    const noteFor = (name) => host.querySelector(`[data-conditional="${name}"]`);
    assert.equal(noteFor("audio_final").hidden, false, "final-only note shows by default");
    assert.equal(noteFor("audio_perseg").hidden, true);

    const toggle = host.querySelector('[data-path="audio_refine.per_segment"]');
    toggle.checked = true;
    change(toggle);

    assert.equal(store.get().audio_refine.per_segment, true);
    assert.equal(noteFor("audio_final").hidden, true);
    assert.equal(noteFor("audio_perseg").hidden, false);
    assert.match(host.querySelector('[data-summary="audio_refine"]').textContent, /Per-segment/);
}

// --------------------------------------------------------------------------
// Locale switching covers the new section.
// --------------------------------------------------------------------------
{
    const { host, view } = mount({ audio_refine: { enabled: true, room: "bar" } });
    view.updateLocale("zh");
    assert.equal(host.querySelector('[data-section="audio_refine"] h3').textContent, "音频空间");
    assert.match(host.querySelector('[data-summary="audio_refine"]').textContent, /酒吧/);
    view.updateLocale("en");
    assert.equal(host.querySelector('[data-section="audio_refine"] h3').textContent, "Audio Room");
}

console.log("postprocess mount tests passed");
