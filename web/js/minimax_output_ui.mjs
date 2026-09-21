import { ResultPlaybackController, audioDriftNeedsSeek, clipGlobalSeconds } from "./minimax_output_player.mjs";
import {
    clipDescriptor,
    clipPositionFor,
    clipStartIndex,
    totalClipFrames,
} from "./minimax_output_clips.mjs";
import { api } from "../../scripts/api.js";

const STYLE_ID = "mmx-output-styles";

const OUTPUT_TEXT = {
    en: {
        live_generation: "Generation",
        live_global: "Global Refine",
        live_face: "Face Refine",

        segment: "Segment",
        multi: "Multi Segment",
        final: "Final Result",

        live_waiting: "Waiting for live preview…",
        result_waiting: "Waiting for generated result…",
        idle: "Idle",

        generated_segment: "Generated Segment",
        available_range: "Available generated range",
        range_start: "Start Segment",
        range_end: "End Segment",
        final_pipeline: "Final pipeline result",

        play: "▶ Play",
        pause: "⏸ Pause",
        volume: "Volume",

        current_run: "Current Run · Idle",
        task_detail: "Task / Segment / Stage / Step",

        pipeline_status: "Pipeline Status",
        pipeline_path:
            "Generation → Global Refine → Assemble → Face Refine → Finalize / Export",

        preview_settings: "Preview Settings",
        director_preview: "Director Preview",
        suppressed: "ComfyUI Default Preview: SUPPRESSED",

        preview_frames: "preview_frames",
        preview_fps: "preview_fps",
        max_resolution: "max_resolution",
        jpeg_quality: "jpeg_quality",
        preview_every: "preview_every",

        save_video: "Save Video",
        auto_save: "Auto-save Final Result",
        output_path: "Output path",
        filename_prefix: "Filename prefix",
        format: "Format",
        codec: "Codec",
        encoding: "Encoding",
        crf: "CRF",
        embed_metadata: "Workflow metadata",
        embed_auto: "Auto (follow ComfyUI)",
        embed_always: "Always embed",
        embed_never: "Never embed",
        save_button: "Save Video",
        save_not_ready: "Final Result is not ready",
        save_ready: "Ready to save",
        save_working: "Saving…",
        save_done: "Saved: {path}",
        save_failed: "Save failed: {error}",
        encoding_auto: "Auto",
        encoding_reencode: "Re-encode",

        final_info: "Final Result Info",
        not_completed: "Not completed",
        report: "Report",
        waiting_report: "Waiting for report…",

        overall_progress: "Overall Progress",
        stage_progress: "Current Stage Progress",

        no_valid: "No valid segments",
        frame: "Frame",
        frames: "frames",
        step: "Step",
        segment_word: "Segment",

        generation: "Generation",
        global_refine: "Global Refine",
        face_refine: "Face Refine",
        assemble: "Assemble",
        finalize: "Finalize / Export",
        upscale: "Upscale",
    },

    zh: {
        live_generation: "一般",
        live_global: "放大",
        live_face: "脸部精修",

        segment: "分段",
        multi: "多段",
        final: "最终结果",

        live_waiting: "等待实时预览…",
        result_waiting: "等待模型生成成果…",
        idle: "待命",

        generated_segment: "已生成片段",
        available_range: "当前有效片段范围",
        range_start: "起始段",
        range_end: "结束段",
        final_pipeline: "最终管线成果",

        play: "▶ 播放",
        pause: "⏸ 暂停",
        volume: "音量",

        current_run: "当前运行 · 待命",
        task_detail: "任务 / 片段 / 阶段 / 步数",

        pipeline_status: "管线状态",
        pipeline_path:
            "生成 → 全局精修 → 组合 → 人脸精修 → 最终处理 / 导出",

        preview_settings: "预览设置",
        director_preview: "Director 预览",
        suppressed: "ComfyUI 默认采样预览：已抑制",

        preview_frames: "预览帧数",
        preview_fps: "预览帧率",
        max_resolution: "最大分辨率",
        jpeg_quality: "JPEG 品质",
        preview_every: "预览间隔",

        save_video: "保存影片",
        auto_save: "自动保存最终结果",
        output_path: "路径",
        filename_prefix: "文件名前缀",
        format: "格式",
        codec: "编码器",
        encoding: "编码模式",
        crf: "CRF",
        embed_metadata: "工作流元数据",
        embed_auto: "自动（跟随 ComfyUI）",
        embed_always: "总是嵌入",
        embed_never: "从不嵌入",
        save_button: "保存影片",
        save_not_ready: "最终结果尚未完成",
        save_ready: "可保存",
        save_working: "正在保存…",
        save_done: "已保存：{path}",
        save_failed: "保存失败：{error}",
        encoding_auto: "自动",
        encoding_reencode: "重新编码",

        final_info: "最终成果信息",
        not_completed: "尚未完成",
        report: "报告",
        waiting_report: "等待报告…",

        overall_progress: "总体进度",
        stage_progress: "当前阶段进度",

        no_valid: "没有有效片段",
        frame: "帧",
        frames: "帧",
        step: "步",
        segment_word: "片段",

        generation: "生成",
        global_refine: "全局精修",
        face_refine: "人脸精修",
        assemble: "组合",
        finalize: "最终处理 / 导出",
        upscale: "放大",
    },
};

function ensureStyles() {
    if (document.getElementById(STYLE_ID)) {
        return;
    }

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
.mmx-output{
    display:grid;
    grid-template-columns:minmax(0,65fr) minmax(320px,35fr);
    gap:10px;
    height:100%;
    min-height:0
}

.mmx-output [hidden]{
    display:none!important
}

.mmx-output-left,
.mmx-output-right{
    min-width:0;
    min-height:0
}

.mmx-output-left{
    display:flex;
    flex-direction:column;
    gap:7px
}

.mmx-output-right{
    display:flex;
    flex-direction:column;
    gap:7px;
    overflow:auto
}

.mmx-result-tabs,
.mmx-live-tabs{
    display:flex;
    gap:5px
}

.mmx-result-tabs button,
.mmx-live-tabs button{
    height:29px;
    min-width:90px;
    border:1px solid #383838;
    border-radius:5px;
    background:#222;
    color:#aaa
}

.mmx-result-tabs button.active,
.mmx-live-tabs button.active{
    border-color:#4fff8f;
    background:#163723;
    color:#4fff8f
}

.mmx-live-tabs button.running:not(.active){
    border-color:#4b765b;
    color:#77ffa4
}

.mmx-result-viewer,
.mmx-live-viewer{
    position:relative;
    flex:1 1 auto;
    min-height:260px;
    display:flex;
    align-items:center;
    justify-content:center;
    overflow:hidden;
    border:1px solid #343434;
    border-radius:8px;
    background:#0d0d0d
}

.mmx-result-viewer img,
.mmx-result-viewer video,
.mmx-live-viewer img,
.mmx-live-viewer video{
    display:block;
    max-width:100%;
    max-height:100%;
    object-fit:contain
}

.mmx-result-empty,
.mmx-live-empty{
    color:#777;
    font-size:12px
}

.mmx-result-badge,
.mmx-live-badge{
    position:absolute;
    left:8px;
    top:8px;
    padding:4px 7px;
    border-radius:4px;
    background:rgba(0,0,0,.72);
    font-size:11px;
    color:#ddd
}

.mmx-result-source,
.mmx-live-source{
    display:flex;
    align-items:center;
    gap:7px;
    min-height:28px;
    font-size:11px;
    color:#aaa
}

.mmx-result-source select,
.mmx-result-source input{
    height:26px;
    border:1px solid #383838;
    border-radius:4px;
    background:#222;
    color:#ddd
}

.mmx-result-range{
    display:flex;
    align-items:center;
    gap:6px
}

.mmx-result-range label{
    display:flex;
    align-items:center;
    gap:5px;
    white-space:nowrap
}

.mmx-result-range select{
    min-width:82px
}

.mmx-result-controls{
    display:grid;
    grid-template-columns:auto minmax(150px,1fr) max-content max-content minmax(150px,auto);
    align-items:center;
    gap:7px;
    min-height:32px
}

.mmx-result-controls button{
    height:28px;
    min-width:58px;
    border:1px solid #3a3a3a;
    border-radius:5px;
    background:#242424;
    color:#ddd
}

.mmx-result-controls input[type=range]{
    width:100%
}

.mmx-result-controls>span{
    white-space:nowrap;
    font-variant-numeric:tabular-nums;
    color:#ddd
}

.mmx-result-controls>label{
    display:grid;
    grid-template-columns:max-content minmax(84px,140px);
    align-items:center;
    gap:7px;
    margin:0;
    white-space:nowrap
}

.mmx-result-controls>label input{
    min-width:84px
}

.mmx-result-info,
.mmx-live-info{
    font-size:11px;
    color:#999
}

.mmx-output-card,
.bd-run-status{
    border:1px solid #333;
    border-radius:7px;
    background:#191919;
    padding:8px
}

.mmx-output-card h4{
    margin:0 0 6px;
    font-size:12px
}

.mmx-output-card>div:not(.mmx-output-report){
    font-size:11px;
    line-height:1.45;
    color:#bbb
}

.mmx-output-card label{
    display:grid;
    grid-template-columns:minmax(125px,1fr) minmax(0,1fr);
    align-items:center;
    gap:8px;
    margin:5px 0;
    font-size:11px;
    color:#aaa
}

.mmx-output-card input,
.mmx-output-card select{
    min-width:0;
    width:100%;
    height:25px;
    border:1px solid #393939;
    border-radius:4px;
    background:#242424;
    color:#ddd;
    box-sizing:border-box
}

.mmx-output-card input[type=checkbox]{
    justify-self:start;
    width:16px;
    height:16px;
    accent-color:#4fff8f
}

.mmx-save-actions{
    display:grid;
    grid-template-columns:minmax(0,1fr) auto;
    gap:8px;
    align-items:center;
    margin-top:7px
}

.mmx-save-actions button{
    height:28px;
    border:1px solid #4b765b;
    border-radius:5px;
    background:#193725;
    color:#77ffa4;
    padding:0 14px
}

.mmx-save-actions button:disabled{
    opacity:.45;
    cursor:not-allowed
}

.mmx-save-status.error{
    color:#ff8a8a
}

.mmx-save-status.success{
    color:#72ee9a
}

.mmx-output-report{
    white-space:pre-wrap;
    max-height:240px;
    overflow:auto;
    font:10px/1.4 ui-monospace,monospace;
    color:#aaa
}

.bd-run-title{
    font-size:12px;
    font-weight:650
}

.bd-run-oom{
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 7px 8px;
    border: 1px solid #7a4a2a;
    border-radius: 5px;
    background: #241a12;
}
.bd-run-oom.hidden {
    display: none;
}
.bd-run-oom-head {
    color: #ffb27a;
    font-size: 10px;
    font-weight: 650;
}
.bd-run-oom-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
}
.bd-run-oom-actions button {
    border: 1px solid #7a4a2a;
    border-radius: 4px;
    background: #2f2116;
    color: #ffd9bb;
    cursor: pointer;
    font-size: 10px;
    padding: 4px 8px;
}
.bd-run-oom-actions button:hover {
    background: #3c2a1c;
    border-color: #a86a3c;
    color: #fff;
}
.bd-run-oom-note {
    color: #a98a70;
    font-size: 9px;
    line-height: 1.35;
}

.bd-run-detail{
    margin:4px 0;
    color:#999;
    font-size:10px
}

.bd-run-bars{
    display:grid;
    gap:4px
}

.bd-run-bar{
    height:6px;
    overflow:hidden;
    border-radius:4px;
    background:#292929
}

.bd-run-bar-fill{
    height:100%;
    background:#4fff8f
}

.bd-run-bar-sub .bd-run-bar-fill{
    background:#69b8ff
}

@media(max-width:1100px){
    .mmx-result-controls{
        grid-template-columns:auto minmax(120px,1fr) max-content max-content
    }

    .mmx-result-controls>label{
        grid-column:1/-1;
        justify-self:end
    }
}

@media(max-width:980px){
    .mmx-output{
        grid-template-columns:1fr
    }

    .mmx-output-right{
        overflow:visible
    }

    .mmx-result-viewer,
    .mmx-live-viewer{
        min-height:220px
    }
}
`;

    document.head.appendChild(style);
}

function dataUrl(b64, mediaType = "image/jpeg") {
    if (b64?.startsWith("data:")) {
        return b64;
    }

    return `data:${mediaType};base64,${b64 || ""}`;
}

function base64Bytes(b64) {
    const clean =
        String(b64 || "")
            .replace(/^data:[^,]*,/, "")
            .replace(/\s+/g, "");

    if (!clean) {
        return null;
    }

    try {
        const binary =
            atob(clean);

        const bytes =
            new Uint8Array(
                binary.length,
            );

        for (let i = 0; i < binary.length; i += 1) {
            bytes[i] = binary.charCodeAt(i);
        }

        return bytes;
    } catch {
        return null;
    }
}

function optionMarkup(values) {
    return values
        .map(
            (value) =>
                `<option value="${String(value)}">${String(value)}</option>`,
        )
        .join("");
}

export function mountOutputUI(
    containers,
    store,
    {
        locale = () => "zh",
        fetchApi = (path, options) => fetch(path, options),
        nodeId = () => "",
    } = {},
) {
    ensureStyles();

    const liveContainer = containers?.live;
    const resultsContainer = containers?.results;

    if (!liveContainer || !resultsContainer) {
        throw new Error(
            "Live Preview and Results containers are required",
        );
    }

    const tx = (key, values = {}) => {
        let text =
            OUTPUT_TEXT[locale() === "en" ? "en" : "zh"][key]
            || key;

        for (const [name, value] of Object.entries(values)) {
            text = text.replace(
                `{${name}}`,
                String(value),
            );
        }

        return text;
    };

    const liveRoot = document.createElement("div");
    liveRoot.className = "mmx-output mmx-live-output";

    liveRoot.innerHTML = `
      <section class="mmx-output-left">
        <div class="mmx-live-tabs">
          <button
            type="button"
            data-live-tab="generation"
            class="active"
            data-output-text="live_generation"
          >一般</button>

          <button
            type="button"
            data-live-tab="global_refine"
            data-output-text="live_global"
          >放大</button>

          <button
            type="button"
            data-live-tab="face_refine"
            data-output-text="live_face"
          >脸部精修</button>
        </div>

        <div class="mmx-live-source">
          <span data-live-source>—</span>
        </div>

        <div class="mmx-live-viewer">
          <img
            data-live-image
            hidden
            alt="Director live preview"
          >

          <video
            data-live-video
            hidden
            playsinline
            muted
          ></video>

          <div
            class="mmx-live-empty"
            data-output-text="live_waiting"
          >等待实时预览…</div>

          <div
            class="mmx-live-badge"
            data-live-badge
            data-output-text="idle"
          >待命</div>
        </div>

        <div
          class="mmx-live-info"
          data-live-info
        >—</div>
      </section>

      <aside class="mmx-output-right">
        <div
          class="bd-run-status idle"
          data-r="run-status"
        >
          <div
            class="bd-run-title"
            data-r="run-title"
            data-output-text="current_run"
          >当前运行 · 待命</div>

          <div
            class="bd-run-detail"
            data-r="run-detail"
            data-output-text="task_detail"
          >任务 / 片段 / 阶段 / 步数</div>

          <!-- Filled in when a run dies on VRAM: the retry belongs next to the
               failure, with the numbers the estimate already computed. -->
          <div class="bd-run-oom hidden" data-r="run-oom"></div>

          <div
            class="bd-run-select-bar hidden"
            data-r="run-select-bar"
          >
            <span data-r="run-select-summary"></span>
          </div>

          <div class="bd-run-bars">
            <div
              class="bd-run-bar"
              data-output-title="overall_progress"
            >
              <div
                class="bd-run-bar-fill"
                data-r="run-overall"
                style="width:0%"
              ></div>
            </div>

            <div
              class="bd-run-bar bd-run-bar-sub"
              data-output-title="stage_progress"
            >
              <div
                class="bd-run-bar-fill"
                data-r="run-phase"
                style="width:0%"
              ></div>
            </div>
          </div>
        </div>

        <section class="mmx-output-card">
          <h4 data-output-text="pipeline_status">
            Pipeline Status
          </h4>

          <div
            data-pipeline-status
            data-output-text="pipeline_path"
          >
            Generation → Global Refine → Assemble → Face Refine → Finalize / Export
          </div>
        </section>

        <section
          class="mmx-output-card"
          data-preview-settings-card
        >
          <h4 data-output-text="preview_settings">
            Preview Settings
          </h4>

          <label>
            <span data-output-text="director_preview">
              Director Preview
            </span>

            <input
              type="checkbox"
              data-preview="enabled"
            >
          </label>

          <label>
            <span data-output-text="preview_frames">
              preview_frames
            </span>

            <input
              type="number"
              min="1"
              max="32"
              data-preview="preview_frames"
            >
          </label>

          <label>
            <span data-output-text="preview_fps">
              preview_fps
            </span>

            <input
              type="number"
              min="1"
              max="60"
              data-preview="preview_fps"
            >
          </label>

          <label>
            <span data-output-text="max_resolution">
              max_resolution
            </span>

            <input
              type="number"
              min="128"
              max="4096"
              data-preview="max_resolution"
            >
          </label>

          <label>
            <span data-output-text="jpeg_quality">
              jpeg_quality
            </span>

            <input
              type="number"
              min="20"
              max="100"
              data-preview="jpeg_quality"
            >
          </label>

          <label>
            <span data-output-text="preview_every">
              preview_every
            </span>

            <input
              type="number"
              min="1"
              max="100"
              data-preview="preview_every"
            >
          </label>

          <div
            class="mmx-result-info"
            data-output-text="suppressed"
          >
            ComfyUI Default Preview: SUPPRESSED
          </div>
        </section>

        <section
          class="mmx-output-card"
          data-mask-check-card
          hidden
        >
          <h4>
            Mask check (window start frame)
          </h4>

          <div
            class="mmx-result-info"
            data-mask-check-label
          >—</div>

          <img
            data-mask-check-img
            alt="Mask check"
            style="max-width:100%;border-radius:4px;display:block;"
          >
        </section>
      </aside>
    `;

    const resultsRoot = document.createElement("div");
    resultsRoot.className = "mmx-output mmx-results-output";

    resultsRoot.innerHTML = `
      <section class="mmx-output-left">
        <div class="mmx-result-tabs">
          <button
            type="button"
            data-result-tab="segment"
            class="active"
            data-output-text="segment"
          >分段</button>

          <button
            type="button"
            data-result-tab="multi"
            data-output-text="multi"
          >多段</button>

          <button
            type="button"
            data-result-tab="final"
            data-output-text="final"
          >最终结果</button>
        </div>

        <div class="mmx-result-source">
          <span
            data-source-label
            data-output-text="generated_segment"
          >已生成片段</span>

          <select
            data-segment-select
          ></select>

          <div
            class="mmx-result-range"
            data-multi-range
            hidden
          >
            <label>
              <span data-output-text="range_start">起始段</span>
              <select data-range-start></select>
            </label>
            <span>→</span>
            <label>
              <span data-output-text="range_end">结束段</span>
              <select data-range-end></select>
            </label>
          </div>

          <span
            data-range-label
            hidden
          ></span>
        </div>

        <div class="mmx-result-viewer">
          <img
            data-result-image
            hidden
            alt="Director result preview"
          >

          <video
            data-result-video
            hidden
            playsinline
            muted
          ></video>

          <div
            class="mmx-result-empty"
            data-output-text="result_waiting"
          >等待模型生成成果…</div>

          <div
            class="mmx-result-badge"
            data-result-badge
            data-output-text="idle"
          >待命</div>
        </div>

        <audio
          data-result-audio
          hidden
        ></audio>

        <div class="mmx-result-controls">
          <button
            type="button"
            data-result-play
            data-output-text="play"
          >▶ 播放</button>

          <input
            type="range"
            data-result-seek
            min="0"
            max="0"
            value="0"
            step="1"
          >

          <span data-result-time>
            0.00 / 0.00
          </span>

          <span data-result-frame>
            帧 0 / 0
          </span>

          <label>
            <span data-output-text="volume">
              音量
            </span>

            <input
              type="range"
              data-result-volume
              min="0"
              max="1"
              value="1"
              step="0.05"
              disabled
            >
          </label>
        </div>

        <div
          class="mmx-result-info"
          data-result-info
        >—</div>
      </section>

      <aside class="mmx-output-right">
        <section
          class="mmx-output-card"
          data-save-video-card
          hidden
        >
          <h4 data-output-text="save_video">
            保存影片
          </h4>

          <label>
            <span data-output-text="auto_save">
              自动保存最终结果
            </span>

            <input
              type="checkbox"
              data-save="auto_save"
            >
          </label>

          <label>
            <span data-output-text="output_path">
              路径
            </span>

            <input
              type="text"
              data-save="output_path"
              placeholder="D:/tool/ComfyUI-aki-v1.6/ComfyUI/output/video"
            >
          </label>

          <label>
            <span data-output-text="filename_prefix">
              文件名前缀
            </span>

            <input
              type="text"
              data-save="filename_prefix"
            >
          </label>

          <label>
            <span data-output-text="format">
              格式
            </span>

            <select data-save="format">
              <option value="auto">auto</option>
              <option value="mp4">mp4</option>
            </select>
          </label>

          <label>
            <span data-output-text="codec">
              编码器
            </span>

            <select data-save="codec">
              <option value="auto">auto</option>
              <option value="h264">h264</option>
            </select>
          </label>

          <label>
            <span data-output-text="encoding">
              编码模式
            </span>

            <select data-save="encoding">
              <option
                value="auto"
                data-output-text="encoding_auto"
              >自动</option>

              <option
                value="re-encode"
                data-output-text="encoding_reencode"
              >重新编码</option>
            </select>
          </label>

          <label>
            <span data-output-text="embed_metadata">
              Workflow metadata
            </span>

            <select data-save="embed_metadata">
              <option
                value="auto"
                data-output-text="embed_auto"
              >Auto (follow ComfyUI)</option>

              <option
                value="always"
                data-output-text="embed_always"
              >Always embed</option>

              <option
                value="never"
                data-output-text="embed_never"
              >Never embed</option>
            </select>
          </label>

          <label data-crf-row>
            <span data-output-text="crf">
              CRF
            </span>

            <input
              type="number"
              min="0"
              max="51"
              step="1"
              data-save="crf"
            >
          </label>

          <div class="mmx-save-actions">
            <span
              class="mmx-save-status"
              data-save-status
              data-output-text="save_not_ready"
            >
              最终结果尚未完成
            </span>

            <button
              type="button"
              data-save-button
              disabled
              data-output-text="save_button"
            >
              保存影片
            </button>
          </div>
        </section>

        <section class="mmx-output-card">
          <h4 data-output-text="final_info">
            最终成果信息
          </h4>

          <div
            data-final-info
            data-output-text="not_completed"
          >
            尚未完成
          </div>
        </section>

        <section class="mmx-output-card">
          <h4 data-output-text="report">
            报告
          </h4>

          <div
            class="mmx-output-report"
            data-report
            data-output-text="waiting_report"
          >
            等待报告…
          </div>
        </section>
      </aside>
    `;

    liveContainer.replaceChildren(liveRoot);
    resultsContainer.replaceChildren(resultsRoot);

    const state = {
        page: "generation",

        liveStage: "generation",
        activeLiveStage: "generation",

        liveByStage: {
            generation: null,
            global_refine: null,
            face_refine: null,
        },

        liveFrozen: {
            generation: "",
            global_refine: "",
            face_refine: "",
        },

        tab: "segment",
        multiStart: null,
        multiEnd: null,
        multiRangeUserSet: false,

        segments: new Map(),
        segmentAudio: new Map(),
        combinedAudio: null,
        final: null,
        finalRecord: null,

        frames: [],
        index: 0,
        playing: false,

        // Preview clip playback. Results arrive as a /view URL to a small
        // all-intra H.264 clip instead of a base64 JPEG per frame, so the
        // browser streams them with HTTP range requests. Multi Segment is a
        // playlist of one clip per segment, played back to back.
        clipPlaylist: [],
        clipFrames: 0,
        clipActive: -1,
        clipPendingSeek: null,
        clipResume: false,

        // Set when the result is a single preview clip. One clip is one
        // continuous video, so it plays through the element rather than the
        // playlist transport; this keeps the clip descriptor around for the
        // scrubbing and clock-sync paths.
        videoClip: null,

        saveStatus: {
            kind: "not_ready",
            value: "",
        },
    };

    const liveImage =
        liveRoot.querySelector("[data-live-image]");

    const liveVideo =
        liveRoot.querySelector("[data-live-video]");

    const liveEmpty =
        liveRoot.querySelector(".mmx-live-empty");

    const liveBadge =
        liveRoot.querySelector("[data-live-badge]");

    const liveInfo =
        liveRoot.querySelector("[data-live-info]");

    const liveSource =
        liveRoot.querySelector("[data-live-source]");

    const pipelineStatus =
        liveRoot.querySelector("[data-pipeline-status]");

    const image =
        resultsRoot.querySelector("[data-result-image]");

    const video =
        resultsRoot.querySelector("[data-result-video]");

    const empty =
        resultsRoot.querySelector(".mmx-result-empty");

    const badge =
        resultsRoot.querySelector("[data-result-badge]");

    const seek =
        resultsRoot.querySelector("[data-result-seek]");

    const timeLabel =
        resultsRoot.querySelector("[data-result-time]");

    const frameLabel =
        resultsRoot.querySelector("[data-result-frame]");

    const infoLabel =
        resultsRoot.querySelector("[data-result-info]");

    const segmentSelect =
        resultsRoot.querySelector("[data-segment-select]");

    const multiRange =
        resultsRoot.querySelector("[data-multi-range]");

    const rangeStart =
        resultsRoot.querySelector("[data-range-start]");

    const rangeEnd =
        resultsRoot.querySelector("[data-range-end]");

    const rangeLabel =
        resultsRoot.querySelector("[data-range-label]");

    const audio =
        resultsRoot.querySelector("[data-result-audio]");

    const volume =
        resultsRoot.querySelector("[data-result-volume]");

    // Currently loaded audio source key: "" (none) | "seg:<n>" | "combined".
    let appliedAudioKey = "";

    // Object URL backing the audio element; revoked on every swap so long runs
    // do not pin every track in memory.
    let audioUrl = "";

    const playButton =
        resultsRoot.querySelector("[data-result-play]");

    const saveCard =
        resultsRoot.querySelector("[data-save-video-card]");

    const saveButton =
        resultsRoot.querySelector("[data-save-button]");

    const saveStatus =
        resultsRoot.querySelector("[data-save-status]");

    const freezeCanvas =
        document.createElement("canvas");

    const freezeContext =
        freezeCanvas.getContext(
            "2d",
            {
                alpha: false,
            },
        );

    const stageKey = (value) => {
        const lower =
            String(value || "")
                .trim()
                .toLowerCase();

        if (
            lower.includes("face")
            && lower.includes("refine")
        ) {
            return "face_refine";
        }

        if (
            lower.includes("global")
            && lower.includes("refine")
        ) {
            return "global_refine";
        }

        return "generation";
    };

    const liveStageText = (key) => {
        if (key === "face_refine") {
            return tx("live_face");
        }

        if (key === "global_refine") {
            return tx("live_global");
        }

        return tx("live_generation");
    };

    const stageText = (value) => {
        const raw =
            String(value || "");

        const lower =
            raw.toLowerCase();

        if (
            lower.includes("global")
            && lower.includes("refine")
        ) {
            return `${tx("global_refine")}${
                lower.includes("upscale")
                    ? ` · ${tx("upscale")}`
                    : ""
            }`;
        }

        if (
            lower.includes("face")
            && lower.includes("refine")
        ) {
            return tx("face_refine");
        }

        if (lower.includes("assemble")) {
            return tx("assemble");
        }

        if (lower.includes("final")) {
            return tx("finalize");
        }

        if (lower.includes("multi")) {
            return tx("multi");
        }

        return lower.includes("generation")
            ? tx("generation")
            : raw || tx("generation");
    };

    const stopLiveMedia = ({
        clear = false,
    } = {}) => {
        liveVideo.pause();
        liveVideo.loop = false;
        liveVideo.autoplay = false;

        if (clear) {
            liveVideo.removeAttribute("src");
            liveVideo.load();

            liveImage.removeAttribute("src");
        }
    };

    const freezeCurrentLive = () => {
        if (
            state.liveStage
            !== state.activeLiveStage
        ) {
            return;
        }

        let source = null;
        let width = 0;
        let height = 0;

        if (
            !liveVideo.hidden
            && liveVideo.videoWidth
            && liveVideo.videoHeight
        ) {
            source = liveVideo;
            width = liveVideo.videoWidth;
            height = liveVideo.videoHeight;
        } else if (
            !liveImage.hidden
            && liveImage.complete
            && liveImage.naturalWidth
            && liveImage.naturalHeight
        ) {
            source = liveImage;
            width = liveImage.naturalWidth;
            height = liveImage.naturalHeight;
        }

        if (
            !source
            || !width
            || !height
            || !freezeContext
        ) {
            return;
        }

        const maxSide = 1024;

        const scale =
            Math.min(
                1,
                maxSide / Math.max(
                    width,
                    height,
                ),
            );

        freezeCanvas.width =
            Math.max(
                1,
                Math.round(width * scale),
            );

        freezeCanvas.height =
            Math.max(
                1,
                Math.round(height * scale),
            );

        try {
            freezeContext.drawImage(
                source,
                0,
                0,
                freezeCanvas.width,
                freezeCanvas.height,
            );

            state.liveFrozen[
                state.liveStage
            ] = freezeCanvas.toDataURL(
                "image/jpeg",
                0.85,
            );
        } catch {
            // Preview freezing is best-effort only.
        }
    };

    const updateLiveTabs = () => {
        liveRoot
            .querySelectorAll("[data-live-tab]")
            .forEach((button) => {
                const key =
                    button.dataset.liveTab;

                button.classList.toggle(
                    "active",
                    key === state.liveStage,
                );

                button.classList.toggle(
                    "running",
                    key === state.activeLiveStage,
                );
            });
    };

    const renderLive = () => {
        updateLiveTabs();

        stopLiveMedia();

        const key =
            state.liveStage;

        const item =
            state.liveByStage[key];

        const isCurrent =
            key === state.activeLiveStage;

        const frozen =
            state.liveFrozen[key];

        liveImage.hidden = true;
        liveVideo.hidden = true;
        liveEmpty.hidden = false;

        if (
            !isCurrent
            && frozen
        ) {
            liveImage.src = frozen;
            liveImage.hidden = false;
            liveEmpty.hidden = true;
        } else if (item) {
            const mediaType =
                item.media_type
                || "image/jpeg";

            const isVideo =
                mediaType.startsWith("video/")
                && item.image_b64;

            if (isVideo) {
                const src =
                    dataUrl(
                        item.image_b64,
                        mediaType,
                    );

                liveVideo.hidden = false;
                liveEmpty.hidden = true;

                liveVideo.controls = false;
                liveVideo.muted = true;
                liveVideo.playsInline = true;

                if (liveVideo.src !== src) {
                    liveVideo.src = src;
                    liveVideo.load();
                }

                if (
                    isCurrent
                    && state.page === "live"
                ) {
                    liveVideo.loop = true;
                    liveVideo.autoplay = true;

                    liveVideo.currentTime = 0;

                    liveVideo
                        .play()
                        .catch(() => {});
                } else {
                    liveVideo.loop = false;
                    liveVideo.autoplay = false;
                    liveVideo.pause();

                    try {
                        liveVideo.currentTime = 0;
                    } catch {
                        // Ignore metadata timing race.
                    }
                }
            } else if (item.image_b64) {
                liveImage.src =
                    dataUrl(
                        item.image_b64,
                        mediaType,
                    );

                liveImage.hidden = false;
                liveEmpty.hidden = true;
            }
        }

        const label =
            liveStageText(key);

        liveSource.textContent =
            key === state.activeLiveStage
                ? `${label} · LIVE`
                : `${label} · Last Preview`;

        if (item) {
            liveBadge.textContent =
                `${label}${
                    item.step
                        ? ` · ${tx("step")} ${item.step}/${item.total_steps || "?"}`
                        : ""
                }`;

            liveInfo.textContent =
                `${item.width || "—"}×${item.height || "—"}`
                + ` · ${Number(item.fps || 12)} fps`
                + `${
                    item.step
                        ? ` · ${tx("step")} ${item.step}/${item.total_steps || "?"}`
                        : ""
                }`;
        } else {
            liveBadge.textContent =
                tx("idle");

            liveInfo.textContent =
                "—";
        }
    };

    const setLiveStage = (key) => {
        if (
            !Object.prototype.hasOwnProperty.call(
                state.liveByStage,
                key,
            )
        ) {
            return;
        }

        if (
            state.liveStage
            === state.activeLiveStage
            && key !== state.liveStage
        ) {
            freezeCurrentLive();
        }

        stopLiveMedia();

        state.liveStage =
            key;

        renderLive();
    };

    liveRoot
        .querySelectorAll("[data-live-tab]")
        .forEach((button) => {
            button.addEventListener(
                "click",
                () => {
                    setLiveStage(
                        button.dataset.liveTab,
                    );
                },
            );
        });

    const availableSegmentIndices = () =>
        [...state.segments.keys()].sort((a, b) => a - b);

    const syncMultiRangeControls = () => {
        const keys = availableSegmentIndices();
        if (!keys.length) {
            state.multiStart = null;
            state.multiEnd = null;
            rangeStart.replaceChildren();
            rangeEnd.replaceChildren();
            rangeLabel.textContent = tx("no_valid");
            return;
        }
        const first = keys[0];
        const last = keys.at(-1);
        if (!state.multiRangeUserSet) {
            state.multiStart = first;
            state.multiEnd = last;
        } else {
            if (!keys.includes(state.multiStart)) state.multiStart = first;
            if (!keys.includes(state.multiEnd)) state.multiEnd = last;
            if (state.multiStart > state.multiEnd) state.multiEnd = state.multiStart;
        }
        const options = keys.map(
            (index) => `<option value="${index}">${tx("segment_word")} ${index + 1}</option>`,
        ).join("");
        rangeStart.innerHTML = options;
        rangeEnd.innerHTML = options;
        rangeStart.value = String(state.multiStart);
        rangeEnd.value = String(state.multiEnd);
        rangeLabel.textContent = `S${state.multiStart + 1} → S${state.multiEnd + 1}`;
    };

    /** Resolve a /view route through the ComfyUI base path (proxies, subpaths). */
    const viewUrl = (route) =>
        typeof api?.apiURL === "function"
            ? api.apiURL(route)
            : route;

    /**
     * Preview clip descriptor for a result, or null when the result still ships
     * the legacy base64 frame array.
     */
    const clipOf = (item) =>
        clipDescriptor(item, viewUrl);

    /** Frame count driving the scrub slider, for either transport. */
    const visibleFrameCount = () =>
        state.isVideo
            ? state.clipFrames
            : state.frames.length;

    /**
     * Point the video element at the clip holding ``index`` and seek to the
     * exact frame. The clips are all-intra, so currentTime = offset / fps lands
     * on the intended frame rather than the nearest earlier keyframe.
     */
    const showClipFrame = (index) => {
        if (!state.clipPlaylist.length) return;

        const {
            position,
            offset,
        } = clipPositionFor(
            state.clipPlaylist,
            index,
        );

        if (position < 0) return;

        const clip =
            state.clipPlaylist[position];

        const seconds =
            offset / Math.max(0.001, clip.fps);

        if (
            state.clipActive
            === position
            && video.getAttribute("src")
                === clip.url
        ) {
            // Same clip: seek directly. Assigning identical src values would
            // restart the decode from scratch.
            if (
                Math.abs(
                    video.currentTime
                    - seconds,
                ) > 0.5 / Math.max(1, clip.fps)
            ) {
                state.clipPendingSeek =
                    seconds;

                try {
                    video.currentTime =
                        seconds;
                } catch {
                    // Element not seekable yet; loadedmetadata retries.
                }
            }

            return;
        }

        state.clipActive =
            position;

        state.clipPendingSeek =
            seconds;

        video.setAttribute(
            "src",
            clip.url,
        );

        video.load();
    };

    const activeResult = () => {
        if (state.tab === "final") {
            return state.final;
        }

        if (state.tab === "segment") {
            return (
                state.segments.get(
                    Number(
                        segmentSelect.value || 0,
                    ),
                )
                || null
            );
        }

        const entries =
            [...state.segments.entries()]
                .sort((a, b) => a[0] - b[0])
                .filter(([index]) => (
                    state.multiStart == null
                    || state.multiEnd == null
                    || (index >= state.multiStart && index <= state.multiEnd)
                ));
        const ordered = entries.map((entry) => entry[1]);

        const clips =
            ordered
                .map(
                    (item) =>
                        clipOf(item),
                )
                .filter(Boolean);

        const stage =
            `Multi Segment S${(state.multiStart ?? entries[0]?.[0] ?? 0) + 1}-S${(state.multiEnd ?? entries.at(-1)?.[0] ?? 0) + 1}`;

        // Prefer the clip transport when every segment in range has one. A
        // partial set falls back to the legacy frame array so the two never mix
        // on one timeline.
        if (
            clips.length
            && clips.length
                === ordered.length
        ) {
            return {
                clipPlaylist:
                    clips,
                frames: [],
                fps:
                    ordered[0]?.fps
                    || 24,
                width:
                    ordered[0]?.width,
                height:
                    ordered[0]?.height,
                stage,
            };
        }

        const frames =
            ordered.flatMap(
                (item) =>
                    item.frames
                    || (
                        item.image_b64
                            ? [item.image_b64]
                            : []
                    ),
            );

        return frames.length
            ? {
                frames,
                fps:
                    ordered[0]?.fps
                    || 24,
                width:
                    ordered[0]?.width,
                height:
                    ordered[0]?.height,
                stage,
            }
            : null;
    };

    /**
     * Index-only paint, called from the playback loop once per animation frame.
     *
     * It must stay cheap. In particular it must NOT call activeResult(): on the
     * Multi Segment tab that rebuilds, sorts and flattens the whole segment list
     * on every call, which used to happen on every frame of playback. It also
     * must not re-derive the video src - a media payload can be several MB and
     * the comparison alone is a full string scan.
     *
     * Everything it needs was cached by the last full renderFrame().
     */
    const paintFrameIndex = (force = false) => {
        const frames =
            state.frames;

        const fps =
            Number(state.fps || 24);

        const count =
            visibleFrameCount();

        if (!state.isVideo && frames.length) {
            // Repaint only when the frame actually changed. A data URL for a
            // full-resolution frame is large enough that re-assigning it every
            // animation frame costs a needless decode.
            if (
                force
                || state.index
                    !== state.paintedIndex
            ) {
                image.src =
                    dataUrl(
                        frames[state.index],
                        frames[state.index]
                            ?.startsWith?.("data:")
                            ? ""
                            : (
                                state.frameMediaType
                                || "image/jpeg"
                            ),
                    );

                state.paintedIndex =
                    state.index;
            }
        }

        seek.value =
            state.index;

        timeLabel.textContent =
            `${(state.index / fps).toFixed(2)}`
            + " / "
            + `${(
                Math.max(
                    0,
                    count - 1,
                )
                / fps
            ).toFixed(2)}`;

        frameLabel.textContent =
            `${tx("frame")} ${
                count
                    ? state.index + 1
                    : 0
            } / ${count}`;
    };

    /**
     * Full render: re-reads the active result and repaints everything that
     * depends on it. Call this on result / tab / range / segment changes only -
     * never from the playback loop.
     */
    const renderFrame = () => {
        const result =
            activeResult();

        // A result carries either a preview clip (a /view URL streamed by the
        // browser) or the legacy base64 frame array. Multi Segment supplies a
        // playlist of one clip per segment.
        const playlist =
            Array.isArray(result?.clipPlaylist)
            && result.clipPlaylist.length
                ? result.clipPlaylist
                : (clipOf(result)
                    ? [clipOf(result)]
                    : []);

        const clipTotal =
            totalClipFrames(playlist);

        // A lone clip is one continuous video, not a playlist. Driving it
        // through the playlist transport left it frozen: that path re-derives
        // the frame index on `seeked` only, which never fires during ordinary
        // playback, so the scrubber and the counters sat on frame 0 while the
        // element played. Only Multi Segment, which really does span several
        // clips, needs playlist bookkeeping.
        const singleClip =
            playlist.length
                === 1
                ? playlist[0]
                : null;

        const frames =
            playlist.length
                ? []
                : result?.frames?.length
                    ? result.frames
                    : result?.image_b64
                        ? [result.image_b64]
                        : [];

        state.frames =
            frames;

        state.clipPlaylist =
            singleClip
                ? []
                : playlist;

        state.videoClip =
            singleClip;

        state.clipFrames =
            singleClip
                ? Math.max(
                    0,
                    Number(singleClip.frames)
                    || 0,
                )
                : clipTotal;

        const total =
            playlist.length
                ? clipTotal
                : frames.length;

        state.index =
            Math.max(
                0,
                Math.min(
                    state.index,
                    Math.max(
                        0,
                        total - 1,
                    ),
                ),
            );

        // Force the next index paint to rewrite the image even when the index
        // itself did not move (the frames behind it may have changed).
        state.paintedIndex =
            -1;

        const mediaType =
            result?.media_type
            || "image/jpeg";

        // An inline video is the legacy single-blob transport; a playlist is a
        // preview clip streamed from /view.
        const inlineVideo =
            !playlist.length
            && mediaType.startsWith("video/")
            && result?.image_b64;

        const isVideo =
            playlist.length > 0
            || !!inlineVideo;

        state.isVideo =
            isVideo;

        state.fps =
            Number(
                result?.fps
                || playlist[0]?.fps
                || 24,
            );

        state.frameMediaType =
            result?.frames?.length
                ? "image/jpeg"
                : mediaType;

        video.hidden =
            !isVideo;

        image.hidden =
            isVideo
            || !frames.length;

        empty.hidden =
            isVideo
            || !!frames.length;

        if (singleClip) {
            // Point the element at the clip once; from then on it owns the
            // clock and the scrubber follows it.
            if (
                video.getAttribute("src")
                !== singleClip.url
            ) {
                video.pause();
                video.setAttribute(
                    "src",
                    singleClip.url,
                );
                video.load();

                // A load rewinds the element to 0, so the index has to follow
                // or the scrubber would claim a frame the picture is not on.
                state.index =
                    0;
            }
        } else if (playlist.length) {
            state.clipResume =
                false;

            showClipFrame(
                state.index,
            );
        } else if (inlineVideo) {
            const src =
                dataUrl(
                    result.image_b64,
                    mediaType,
                );

            // Compare the attribute we set, not the .src property: the
            // property re-serialises the whole data URL on every read.
            if (
                video.getAttribute("src")
                !== src
            ) {
                video.pause();
                video.setAttribute(
                    "src",
                    src,
                );
                video.load();
            }
        } else {
            video.pause();
        }

        seek.max =
            Math.max(
                0,
                total - 1,
            );

        infoLabel.textContent =
            result
                ? `${result.width || "—"}×${result.height || "—"}`
                    + ` · ${state.fps} fps`
                    + ` · ${
                        total
                        || (
                            isVideo
                                ? "video"
                                : 0
                        )
                    } ${tx("frames")}`
                : "—";

        badge.textContent =
            result
                ? `${stageText(result.stage)}${
                    result.step
                        ? ` · ${tx("step")} ${result.step}/${result.total_steps || "?"}`
                        : ""
                }`
                : tx("idle");

        paintFrameIndex(true);
    };

    const playback =
        new ResultPlaybackController({
            audio,

            // Read the fps cached by the last full render, not activeResult():
            // the controller consults this several times per animation frame.
            getFps: () =>
                Number(
                    state.fps
                    || 24,
                ),

            // Must report the transport actually in use. On the preview-clip
            // path state.frames is empty *by design* and the timeline length
            // lives in state.clipFrames, so returning state.frames.length gave
            // the transport a zero-frame timeline and a play button that did
            // nothing. visibleFrameCount() already draws that distinction.
            getFrameCount: () =>
                visibleFrameCount(),

            onFrame(index) {
                state.index =
                    index;

                // Index-only repaint. Calling renderFrame() here re-derived the
                // whole result - on the Multi Segment tab that meant sorting and
                // flattening every segment on each animation frame, which is
                // what made playback stall.
                paintFrameIndex();
            },

            onPlaying(playing) {
                state.playing =
                    playing;

                playButton.textContent =
                    tx(
                        playing
                            ? "pause"
                            : "play",
                    );
            },
        });

    const stop = () => {
        playback.stop();
        video.pause();

        state.playing =
            false;

        playButton.textContent =
            tx("play");
    };

    const renderSaveStatus = () => {
        const {
            kind,
            value,
        } = state.saveStatus;

        saveStatus.className =
            `mmx-save-status ${
                kind === "failed"
                    ? "error"
                    : kind === "done"
                        ? "success"
                        : ""
            }`;

        saveStatus.textContent =
            kind === "ready"
                ? tx("save_ready")
                : kind === "working"
                    ? tx("save_working")
                    : kind === "done"
                        ? tx(
                            "save_done",
                            {
                                path: value,
                            },
                        )
                        : kind === "failed"
                            ? tx(
                                "save_failed",
                                {
                                    error: value,
                                },
                            )
                            : tx(
                                "save_not_ready",
                            );
    };

    const setTab = (tab) => {
        if (
            ![
                "segment",
                "multi",
                "final",
            ].includes(tab)
        ) {
            return;
        }

        stop();

        state.tab =
            tab;

        state.index =
            0;

        resultsRoot
            .querySelectorAll(
                "[data-result-tab]",
            )
            .forEach(
                (button) =>
                    button.classList.toggle(
                        "active",
                        button.dataset.resultTab
                            === tab,
                    ),
            );

        segmentSelect.hidden =
            tab !== "segment";

        multiRange.hidden =
            tab !== "multi";

        rangeLabel.hidden = true;

        if (tab === "multi") syncMultiRangeControls();

        saveCard.hidden =
            !["multi", "final"].includes(tab);

        resultsRoot
            .querySelector(
                "[data-source-label]",
            )
            .textContent =
                tx(
                    tab === "segment"
                        ? "generated_segment"
                        : tab === "multi"
                            ? "available_range"
                            : "final_pipeline",
                );

        syncAudioSource();
        renderFrame();
    };

    resultsRoot
        .querySelectorAll(
            "[data-result-tab]",
        )
        .forEach(
            (button) =>
                button.addEventListener(
                    "click",
                    () =>
                        setTab(
                            button.dataset.resultTab,
                        ),
                ),
        );

    segmentSelect.addEventListener(
        "change",
        () => {
            stop();

            state.index =
                0;

            syncAudioSource();
            renderFrame();
        },
    );

    rangeStart.addEventListener("change", () => {
        stop();
        state.multiRangeUserSet = true;
        state.multiStart = Number(rangeStart.value);
        if (state.multiEnd == null || state.multiStart > state.multiEnd) {
            state.multiEnd = state.multiStart;
        }
        state.index = 0;
        syncMultiRangeControls();
        renderFrame();
    });

    rangeEnd.addEventListener("change", () => {
        stop();
        state.multiRangeUserSet = true;
        state.multiEnd = Number(rangeEnd.value);
        if (state.multiStart == null || state.multiEnd < state.multiStart) {
            state.multiStart = state.multiEnd;
        }
        state.index = 0;
        syncMultiRangeControls();
        renderFrame();
    });

    seek.addEventListener(
        "input",
        () => {
            const value =
                Number(seek.value);

            // Clips are all-intra, so seeking to offset / fps lands on the
            // intended frame instead of the nearest earlier keyframe.
            if (state.clipPlaylist.length) {
                state.index =
                    value;

                // Scrubbing cancels a queued playlist advance.
                state.clipResume =
                    false;

                showClipFrame(
                    value,
                );

                paintFrameIndex(true);
                return;
            }

            if (state.videoClip) {
                // One clip: the element is the transport, so a scrub has to move
                // the element. Handing it to the frame controller moved a
                // wall-clock index that the picture knows nothing about.
                state.index =
                    value;

                try {
                    video.currentTime =
                        value
                        / Math.max(
                            0.001,
                            Number(state.fps || 24),
                        );
                } catch {
                    // Not seekable yet; the next render retries.
                }

                paintFrameIndex(true);
                return;
            }

            playback.seek(
                value,
            );
        },
    );

    volume.addEventListener(
        "input",
        () => {
            audio.volume =
                Number(
                    volume.value,
                );
        },
    );

    // A video result has no native controls, so the Play button has to drive the
    // element itself. Keep the button label in step with the element's own state
    // (which also changes on ended / external pause).
    const syncVideoPlayState = () => {
        if (!state.isVideo) return;

        state.playing =
            !video.paused
            && !video.ended;

        playButton.textContent =
            tx(
                state.playing
                    ? "pause"
                    : "play",
            );

        // A preview clip carries picture only - the Director delivers audio on a
        // separate element. The frame-array player used to start that audio, so
        // clip playback has to do it here or the result would play silent.
        // A single clip counts too: it is still a clip, just a lone one.
        if (
            !state.clipPlaylist.length
            && !state.videoClip
        ) {
            return;
        }

        if (
            !String(
                audio.currentSrc
                || audio.src
                || "",
            ).trim()
        ) {
            return;
        }

        if (state.playing) {
            syncAudioToVideo();
            audio.play?.().catch?.(
                () => {},
            );
            return;
        }

        audio.pause();
    };

    /**
     * Keep the separate audio element aligned with the video.
     *
     * The time base is the element's **live** clock, never `state.index`: that index is
     * refreshed by a later `timeupdate` listener, so on this tick it is up to one update
     * (~0.25 s) old. A target that lags the audio makes the correction seek *backwards*
     * on every tick, replaying a small chunk of sound over and over - the preview
     * "stutter" that the exported file, which has no such clock, never had.
     */
    const syncAudioToVideo = () => {
        if (
            (
                !state.clipPlaylist.length
                && !state.videoClip
            )
            || video.paused
        ) {
            return;
        }

        if (
            audio.paused
            || !Number.isFinite(
                audio.duration,
            )
        ) {
            return;
        }

        const fps =
            Math.max(
                0.001,
                Number(state.fps || 24),
            );

        const seconds =
            onSingleClipTransport()
                ? Math.max(
                    0,
                    Number(video.currentTime || 0),
                )
                : clipGlobalSeconds(
                    clipStartIndex(
                        state.clipPlaylist,
                        state.clipActive,
                    ) / fps,
                    video.currentTime,
                );

        // Correct real drift only - and only in the direction that cannot be heard as
        // a repeat (see audioDriftNeedsSeek).
        const drift =
            Number(audio.currentTime || 0)
            - seconds;

        if (!audioDriftNeedsSeek(drift)) {
            return;
        }

        try {
            audio.currentTime =
                seconds;
        } catch {
            // Audio not seekable yet; the next tick retries.
        }
    };

    const reportVideoProgress = () => {
        if (!state.isVideo) return;

        // Clip playback reports time through paintFrameIndex() using the global
        // frame index, because one clip's duration is not the timeline length.
        if (state.clipPlaylist.length) return;

        const duration =
            Number(video.duration);

        if (
            !Number.isFinite(duration)
            || duration <= 0
        ) {
            return;
        }

        timeLabel.textContent =
            `${video.currentTime.toFixed(2)}`
            + " / "
            + `${duration.toFixed(2)}`;
    };

    video.addEventListener(
        "play",
        syncVideoPlayState,
    );

    video.addEventListener(
        "pause",
        syncVideoPlayState,
    );

    video.addEventListener(
        "ended",
        syncVideoPlayState,
    );

    video.addEventListener(
        "timeupdate",
        reportVideoProgress,
    );

    video.addEventListener(
        "timeupdate",
        syncAudioToVideo,
    );

    /**
     * True when the result plays as one clip through the video element, so the
     * element's own clock is the time base instead of a playlist position.
     */
    const onSingleClipTransport = () =>
        !!state.videoClip
        && !state.clipPlaylist.length;

    /**
     * Follow the element's own clock. When a clip is playing the browser is
     * authoritative for which frame is on screen, so the slider and counters
     * are derived from currentTime rather than driving it.
     */
    const syncIndexFromVideo = () => {
        if (onSingleClipTransport()) {
            const fps =
                Math.max(
                    0.001,
                    Number(state.fps || 24),
                );

            const count =
                Math.max(
                    0,
                    Number(state.clipFrames || 0),
                );

            state.index =
                Math.max(
                    0,
                    Math.min(
                        Math.max(
                            0,
                            count - 1,
                        ),
                        Math.round(
                            Number(video.currentTime || 0)
                            * fps,
                        ),
                    ),
                );

            paintFrameIndex();

            return;
        }

        if (!state.clipPlaylist.length) return;

        const position =
            state.clipActive;

        const clip =
            state.clipPlaylist[position];

        if (!clip) return;

        const local =
            Math.round(
                Number(video.currentTime || 0)
                * Math.max(0.001, clip.fps),
            );

        state.index =
            clipStartIndex(
                state.clipPlaylist,
                position,
            )
            + Math.max(
                0,
                Math.min(
                    Math.max(0, clip.frames - 1),
                    local,
                ),
            );

        paintFrameIndex();
    };

    video.addEventListener(
        "seeked",
        syncIndexFromVideo,
    );

    // `timeupdate` is what keeps the bar moving. Registering this only on
    // `seeked` meant the index never advanced during ordinary playback, so a
    // result that was playing perfectly well still showed 0.00 and frame 1.
    // Registered last so its index-derived labels win over the element's own.
    video.addEventListener(
        "timeupdate",
        syncIndexFromVideo,
    );

    // A seek requested before the element has metadata has to wait: assigning
    // currentTime on a not-yet-loaded media element is silently ignored.
    video.addEventListener(
        "loadedmetadata",
        () => {
            if (state.clipPendingSeek != null) {
                const seconds =
                    state.clipPendingSeek;

                state.clipPendingSeek =
                    null;

                try {
                    video.currentTime =
                        seconds;
                } catch {
                    // Element rejected the seek (detached); the next render retries.
                }
            }

            // Playlist advance: start the next clip only once it is positioned,
            // otherwise it would briefly play from frame 0 before the seek lands.
            if (state.clipResume) {
                state.clipResume =
                    false;

                video.play?.().catch?.(
                    () => {},
                );
            }
        },
    );

    // Multi Segment: continue into the next clip when one finishes.
    video.addEventListener(
        "ended",
        () => {
            if (!state.clipPlaylist.length) return;

            const next =
                state.clipActive + 1;

            if (next >= state.clipPlaylist.length) return;

            state.index =
                clipStartIndex(
                    state.clipPlaylist,
                    next,
                );

            state.clipResume =
                true;

            showClipFrame(
                state.index,
            );
        },
    );

    // A clip transition (or a slow read) stalls the *video* while the audio keeps
    // rolling. Let the audio wait with it: running ahead only earns a backwards
    // correction, and a backwards correction is heard as a repeated chunk.
    video.addEventListener(
        "waiting",
        () => {
            if (!state.playing) return;
            if (
                !state.clipPlaylist.length
                && !state.videoClip
            ) {
                return;
            }
            audio.pause();
        },
    );

    video.addEventListener(
        "playing",
        () => {
            if (!state.playing) return;
            if (
                !state.clipPlaylist.length
                && !state.videoClip
            ) {
                return;
            }
            try {
                syncAudioToVideo();
            } catch {
                // No metadata yet; the next tick aligns it.
            }
            audio.play?.().catch?.(
                () => {},
            );
        },
    );

    playButton.addEventListener(
        "click",
        () => {
            // Video results play through the element; frame sequences play
            // through the frame-by-frame controller.
            if (state.isVideo) {
                if (video.paused) {
                    video.play?.().catch?.(
                        () => {},
                    );
                } else {
                    video.pause();
                }

                return;
            }

            if (state.playing) {
                playback.pause();
            } else {
                playback.play(
                    state.index,
                );
            }
        },
    );

    const refreshSettings = (config) => {
        liveRoot
            .querySelectorAll(
                "[data-preview]",
            )
            .forEach((input) => {
                const value =
                    config.preview[
                        input.dataset.preview
                    ];

                if (
                    input.type
                    === "checkbox"
                ) {
                    input.checked =
                        !!value;
                } else {
                    input.value =
                        value ?? "";
                }
            });

        resultsRoot
            .querySelectorAll(
                "[data-save]",
            )
            .forEach((input) => {
                const value =
                    config.save[
                        input.dataset.save
                    ];

                if (
                    input.type
                    === "checkbox"
                ) {
                    input.checked =
                        !!value;
                } else {
                    input.value =
                        value ?? "";
                }
            });

        resultsRoot
            .querySelector(
                "[data-crf-row]",
            )
            .hidden =
                config.save.encoding
                !== "re-encode";
    };

    liveRoot
        .querySelectorAll(
            "[data-preview]",
        )
        .forEach((input) => {
            input.addEventListener(
                "change",
                () => {
                    store.patch(
                        "preview",
                        input.dataset.preview,
                        input.type
                            === "checkbox"
                            ? input.checked
                            : Number(
                                input.value,
                            ),
                    );
                },
            );
        });

    resultsRoot
        .querySelectorAll(
            "[data-save]",
        )
        .forEach((input) => {
            input.addEventListener(
                "change",
                () => {
                    const value =
                        input.type
                        === "checkbox"
                            ? input.checked
                            : input.type
                                === "number"
                                ? Number(
                                    input.value,
                                )
                                : input.value;

                    store.patch(
                        "save",
                        input.dataset.save,
                        value,
                    );
                },
            );
        });

    const unsubscribe =
        store.subscribe(
            refreshSettings,
        );

    refreshSettings(
        store.get(),
    );

    const consumePreview = (detail = {}) => {
        const item = {
            ...detail,
            frames:
                detail.frames
                || [],
            image_b64:
                detail.image_b64
                || detail.imageB64
                || "",
        };

        if (detail.live) {
            const key =
                stageKey(
                    detail.stage,
                );

            if (
                state.activeLiveStage
                !== key
                && state.liveStage
                === state.activeLiveStage
            ) {
                freezeCurrentLive();
            }

            stopLiveMedia();

            state.liveByStage[key] =
                item;

            state.liveFrozen[key] =
                "";

            state.activeLiveStage =
                key;

            state.liveStage =
                key;

            pipelineStatus.textContent =
                `${tx("segment_word")} ${
                    Number(
                        detail.segment_index
                        || 0,
                    ) + 1
                }`
                + ` · ${stageText(detail.stage)}`
                + `${
                    detail.step
                        ? ` · ${tx("step")} ${detail.step}/${detail.total_steps || "?"}`
                        : ""
                }`;

            renderLive();

            return;
        }

        if (
            detail.result_kind
            === "final"
        ) {
            state.final =
                item;

            const finalInfo =
                resultsRoot.querySelector(
                    "[data-final-info]",
                );

            // The clip transport ships no frame array, so take the count from
            // the clip itself when one is present; otherwise it would read
            // "0 frames" next to a clip that plays perfectly well.
            const finalClip =
                clipOf(item);

            finalInfo.textContent =
                `${item.width || "—"}×${item.height || "—"}`
                + ` · ${
                    finalClip
                        ? finalClip.frames
                        : item.frames.length
                } ${tx("frames")}`
                + ` · ${item.fps || 24} fps`;

            finalInfo.dataset.hasResult =
                "1";
        } else {
            state.segments.set(
                Number(
                    detail.segment_index
                    || 0,
                ),
                item,
            );

            segmentSelect.innerHTML =
                [...state.segments.keys()]
                    .sort(
                        (a, b) =>
                            a - b,
                    )
                    .map(
                        (index) =>
                            `<option value="${index}">${tx("segment_word")} ${index + 1}</option>`,
                    )
                    .join("");

            const keys =
                [...state.segments.keys()]
                    .sort(
                        (a, b) =>
                            a - b,
                    );

            rangeLabel.textContent =
                keys.length
                    ? `S${keys[0] + 1} → S${keys.at(-1) + 1}`
                    : tx("no_valid");
            syncMultiRangeControls();
        }

        renderFrame();
    };

    const setFinalRecord = (detail = {}) => {
        state.finalRecord =
            detail.ready === false
            || !detail.run_id
                ? null
                : {
                    ...detail,
                };

        saveButton.disabled =
            !state.finalRecord;

        const auto =
            detail.auto_save
            || detail.auto_save_result;

        if (auto?.ok) {
            state.saveStatus = {
                kind: "done",
                value:
                    auto.path
                    || auto.filename
                    || "",
            };
        } else if (
            auto
            && auto.ok === false
        ) {
            state.saveStatus = {
                kind: "failed",
                value:
                    auto.error
                    || detail.auto_save_error
                    || "Unknown error",
            };
        } else if (detail.error) {
            state.saveStatus = {
                kind: "failed",
                value: detail.error,
            };
        } else {
            state.saveStatus = {
                kind:
                    state.finalRecord
                        ? "ready"
                        : "not_ready",
                value: "",
            };
        }

        renderSaveStatus();
    };

    const clear = () => {
        stop();
        stopLiveMedia({
            clear: true,
        });

        const maskCard = liveRoot.querySelector("[data-mask-check-card]");
        const maskImg = liveRoot.querySelector("[data-mask-check-img]");
        if (maskCard) maskCard.hidden = true;
        if (maskImg) maskImg.removeAttribute("src");

        state.liveStage =
            "generation";

        state.activeLiveStage =
            "generation";

        state.liveByStage = {
            generation: null,
            global_refine: null,
            face_refine: null,
        };

        state.liveFrozen = {
            generation: "",
            global_refine: "",
            face_refine: "",
        };

        state.segments.clear();
        state.segmentAudio.clear();
        state.combinedAudio = null;
        appliedAudioKey = "";
        state.multiStart = null;
        state.multiEnd = null;
        state.multiRangeUserSet = false;
        syncMultiRangeControls();

        state.final =
            null;

        state.finalRecord =
            null;

        state.frames =
            [];

        state.index =
            0;

        segmentSelect.replaceChildren();

        audio.removeAttribute(
            "src",
        );

        audio.load?.();

        volume.disabled =
            true;

        saveButton.disabled =
            true;

        state.saveStatus = {
            kind: "not_ready",
            value: "",
        };

        renderSaveStatus();

        const finalInfo =
            resultsRoot.querySelector(
                "[data-final-info]",
            );

        delete finalInfo.dataset.hasResult;

        finalInfo.textContent =
            tx("not_completed");

        const report =
            resultsRoot.querySelector(
                "[data-report]",
            );

        delete report.dataset.hasReport;

        report.textContent =
            tx("waiting_report");

        renderLive();
        renderFrame();
    };

    const setReport = (text) => {
        const report =
            resultsRoot.querySelector(
                "[data-report]",
            );

        report.textContent =
            String(
                text || "",
            );

        report.dataset.hasReport =
            text
                ? "1"
                : "";
    };

    const viewAudioSource = () => {
        if (state.tab === "segment") {
            const index =
                Number(segmentSelect.value || 0);

            const entry =
                state.segmentAudio.get(index);

            return entry
                ? {
                    key: `seg:${index}`,
                    b64: entry.b64,
                    type:
                        entry.type
                        || "audio/wav",
                }
                : null;
        }

        return state.combinedAudio
            ? {
                key: "combined",
                b64: state.combinedAudio.b64,
                type:
                    state.combinedAudio.type
                    || "audio/wav",
            }
            : null;
    };

    const syncAudioSource = () => {
        const source =
            viewAudioSource();

        const nextKey =
            source
                ? source.key
                : "";

        if (nextKey === appliedAudioKey) {
            return;
        }

        const wasPlaying =
            state.playing;

        appliedAudioKey =
            nextKey;

        // The clock source is changing under an active player; stop it so
        // the audio/video clocks cannot desync.
        if (wasPlaying) {
            stop();
        }

        if (!source) {
            audio.removeAttribute(
                "src",
            );

            audio.load?.();

            volume.disabled =
                true;
            return;
        }

        // Result audio arrives as base64 WAV. A data: URL has to be parsed and
        // re-seeked out of a giant attribute string, which crackles and clicks
        // when the drift helper seeks; a Blob URL is seekable and streamed.
        const bytes =
            base64Bytes(source.b64);

        if (
            !bytes
            || bytes.length <= 44
        ) {
            appliedAudioKey = "";
            audio.removeAttribute(
                "src",
            );
            audio.load?.();

            volume.disabled =
                true;

            return;
        }

        if (audioUrl) {
            URL.revokeObjectURL(
                audioUrl,
            );
        }

        audioUrl =
            URL.createObjectURL(
                new Blob(
                    [bytes],
                    {
                        type:
                            source.type
                            || "audio/wav",
                    },
                ),
            );

        audio.src =
            audioUrl;

        audio.volume =
            Number(
                volume.value,
            );

        volume.disabled =
            false;
    };

    const setAudio = (detail = {}) => {
        if (!detail.audio_b64) {
            return;
        }

        const mediaType =
            detail.media_type
            || "audio/wav";

        if (detail.segment_index != null) {
            const index =
                Number(
                    detail.segment_index,
                );

            state.segmentAudio.set(
                index,
                {
                    b64: detail.audio_b64,
                    type: mediaType,
                },
            );

            // Only swap the live audio element when this is the segment
            // currently shown; otherwise just cache it for when the user
            // selects that segment.
            if (
                state.tab === "segment"
                && Number(segmentSelect.value || 0) === index
            ) {
                syncAudioSource();
            }
            return;
        }

        // Whole-run combined audio (sent once when the job completes).
        state.combinedAudio = {
            b64: detail.audio_b64,
            type: mediaType,
        };

        // Used by Multi / Final views; never clobber a per-segment source
        // while a single segment is being watched.
        if (state.tab !== "segment") {
            syncAudioSource();
        }
    };

    const setPipelineStatus = (detail = {}) => {
        const phase =
            String(
                detail.phase
                || "plan",
            );

        const stage =
            phase === "global_upscale"
            || phase === "global_refine"
                ? tx("global_refine")
                : phase === "face_refine"
                    ? tx("face_refine")
                    : phase === "assemble"
                        ? tx("assemble")
                        : phase === "finalize"
                            || phase === "finish"
                            ? tx("finalize")
                            : tx("generation");

        const step =
            detail.phase_max > 1
                ? ` · ${tx("step")} ${detail.phase_value}/${detail.phase_max}`
                : "";

        pipelineStatus.textContent =
            `${tx("segment_word")} ${
                detail.timeline_segment
                || detail.segment
                || 1
            }/${
                detail.timeline_segment_total
                || detail.segment_total
                || 1
            } · ${stage}${step}`;
    };

    const setPageVisibility = (page) => {
        state.page =
            String(
                page || "",
            );

        if (state.page !== "live") {
            if (
                state.liveStage
                === state.activeLiveStage
            ) {
                freezeCurrentLive();
            }

            stopLiveMedia();
        } else {
            renderLive();
        }

        if (state.page !== "results") {
            stop();
        }
    };

    saveButton.addEventListener(
        "click",
        async () => {
            if (
                !state.finalRecord
                || saveButton.disabled
            ) {
                return;
            }

            state.saveStatus = {
                kind: "working",
                value: "",
            };

            renderSaveStatus();

            saveButton.disabled =
                true;

            try {
                const response =
                    await fetchApi(
                        "/minimax/motion-director/save_video",
                        {
                            method: "POST",
                            headers: {
                                "Content-Type":
                                    "application/json",
                            },
                            body:
                                JSON.stringify({
                                    node_id:
                                        String(
                                            nodeId()
                                            || state.finalRecord.node_id
                                            || "",
                                        ),
                                    run_id:
                                        state.finalRecord.run_id,
                                    save:
                                        store.get().save,
                                    segment_range:
                                        state.tab === "multi"
                                            ? {
                                                start: state.multiStart,
                                                end: state.multiEnd,
                                            }
                                            : null,
                                }),
                        },
                    );

                const result =
                    await response.json();

                if (
                    !response.ok
                    || !result.ok
                ) {
                    throw new Error(
                        result.error
                        || `HTTP ${response.status}`,
                    );
                }

                state.saveStatus = {
                    kind: "done",
                    value:
                        result.path
                        || result.filename
                        || "",
                };
            } catch (error) {
                state.saveStatus = {
                    kind: "failed",
                    value:
                        error?.message
                        || String(error),
                };
            } finally {
                saveButton.disabled =
                    !state.finalRecord;

                renderSaveStatus();
            }
        },
    );

    const updateLocale = () => {
        for (const root of [
            liveRoot,
            resultsRoot,
        ]) {
            root
                .querySelectorAll(
                    "[data-output-text]",
                )
                .forEach((element) => {
                    const key =
                        element.dataset.outputText;

                    if (
                        key === "not_completed"
                        && element.dataset.hasResult
                    ) {
                        return;
                    }

                    if (
                        key === "waiting_report"
                        && element.dataset.hasReport
                    ) {
                        return;
                    }

                    if (
                        key
                        && OUTPUT_TEXT[
                            locale() === "en"
                                ? "en"
                                : "zh"
                        ][key]
                    ) {
                        element.textContent =
                            tx(key);
                    }
                });

            root
                .querySelectorAll(
                    "[data-output-title]",
                )
                .forEach((element) => {
                    element.title =
                        tx(
                            element.dataset.outputTitle,
                        );
                });
        }

        resultsRoot
            .querySelector(
                "[data-source-label]",
            )
            .textContent =
                tx(
                    state.tab === "segment"
                        ? "generated_segment"
                        : state.tab === "multi"
                            ? "available_range"
                            : "final_pipeline",
                );

        for (const select of [segmentSelect, rangeStart, rangeEnd]) {
            for (const option of select.options) {
                option.textContent =
                    `${tx("segment_word")} ${Number(option.value) + 1}`;
            }
        }

        playButton.textContent =
            tx(
                state.playing
                    ? "pause"
                    : "play",
            );

        renderSaveStatus();
        renderLive();
        renderFrame();
    };

    (async () => {
        try {
            const response =
                await fetchApi(
                    "/minimax/motion-director/postprocess_capabilities",
                );

            if (!response?.ok) {
                return;
            }

            const values =
                (await response.json())
                    ?.video_save
                || {};

            const current =
                store.get().save;

            const format =
                resultsRoot.querySelector(
                    '[data-save="format"]',
                );

            const codec =
                resultsRoot.querySelector(
                    '[data-save="codec"]',
                );

            if (values.formats?.length) {
                format.innerHTML =
                    optionMarkup(
                        values.formats,
                    );
            }

            if (values.codecs?.length) {
                codec.innerHTML =
                    optionMarkup(
                        values.codecs,
                    );
            }

            format.value =
                current.format;

            codec.value =
                current.codec;
        } catch {
            // Capability discovery is optional.
        }
    })();

    const setMaskCheck = (detail = {}) => {
        const card = liveRoot.querySelector("[data-mask-check-card]");
        const img = liveRoot.querySelector("[data-mask-check-img]");
        const label = liveRoot.querySelector("[data-mask-check-label]");
        if (!card || !img) return;
        const uri =
            detail.image_b64
            || detail.imageB64
            || "";
        if (uri) {
            img.src = uri;
            if (label) {
                label.textContent =
                    detail.label
                    || "Mask check";
            }
            card.hidden = false;
        } else {
            card.hidden = true;
            img.removeAttribute("src");
            if (label) {
                label.textContent = "—";
            }
        }
    };

    updateLocale();
    setTab("segment");
    renderSaveStatus();
    renderLive();

    return {
        root: resultsRoot,
        liveRoot,
        resultsRoot,
        state,

        consumePreview,
        setMaskCheck,
        clear,
        setReport,
        setAudio,
        setFinalRecord,
        setPipelineStatus,
        setTab,
        setLiveStage,
        setPageVisibility,
        updateLocale,

        runStatusEl:
            liveRoot.querySelector(
                '[data-r="run-status"]',
            ),

        runTitleEl:
            liveRoot.querySelector(
                '[data-r="run-title"]',
            ),

        runDetailEl:
            liveRoot.querySelector(
                '[data-r="run-detail"]',
            ),

        runOomEl:
            liveRoot.querySelector(
                '[data-r="run-oom"]',
            ),

        runOverallEl:
            liveRoot.querySelector(
                '[data-r="run-overall"]',
            ),

        runPhaseEl:
            liveRoot.querySelector(
                '[data-r="run-phase"]',
            ),

        runSelectBar:
            liveRoot.querySelector(
                '[data-r="run-select-bar"]',
            ),

        runSelectSummary:
            liveRoot.querySelector(
                '[data-r="run-select-summary"]',
            ),

        destroy() {
            stop();
            stopLiveMedia({
                clear: true,
            });

            playback.destroy();
            unsubscribe();

            const id =
                String(
                    nodeId()
                    || "",
                );

            if (id) {
                fetchApi(
                    "/minimax/motion-director/release_video",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json",
                        },
                        body:
                            JSON.stringify({
                                node_id: id,
                            }),
                    },
                ).catch?.(
                    () => {},
                );
            }
        },
    };
}