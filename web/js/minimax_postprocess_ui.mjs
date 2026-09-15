const ROOM_NAMES = ["dry", "bedroom", "bathroom", "bar", "office", "car", "hall", "cathedral", "outdoor"];

// Short forms for the one-line summary; the dropdown uses the longer labels.
const ROOM_SHORT = {
    dry: ["Dry", "干声"], bedroom: ["Bedroom", "卧室"], bathroom: ["Bathroom", "浴室"],
    bar: ["Bar", "酒吧"], office: ["Office", "办公室"], car: ["Car", "车内"],
    hall: ["Hall", "大厅"], cathedral: ["Cathedral", "教堂"], outdoor: ["Outdoor", "室外"],
};

const DEFAULT_CONFIG = Object.freeze({
    version: 11,
    global_refine: {
        enabled: false, mode: "refine", second_sampling_enabled: true, result_previews_enabled: false, denoise: 0.25, steps: 0,
        allow_refine_on_external_patch: false, export_comparison: false,
        seed_mode: "inherit", seed_offset: 1, skip_fl2v: false,
        upscale_method: "lanczos", upscale_model: "",
        latent_upscale_model: "", latent_upscale_precision: "fp16", latent_upscale_device: "cuda",
        vsr_quality: "high",
        resolution_mode: "follow_director", aspect: "16:9", megapixels: 1,
        width: 1376, height: 768,
        rtx_deblur_enabled: false, rtx_deblur_quality: "medium", rtx_deblur_strength: 1,
        tiled_refine: false, tile_size: 512, tile_overlap: 96,
        temporal_split: false, temporal_chunk_frames: 136, temporal_overlap_frames: 17,
    },
    face_refine: {
        enabled: false, detector: "ultralytics", detector_model: "", confidence: 0.35,
        select: "largest", crop_factor: 2.5, canvas_mode: "auto_capped_768", canvas_size: 768,
        smooth_method: "gaussian", smooth_window: 21, size_smooth_window: 51, size_mode: "adaptive",
        adaptive: true, base_denoise: 0.45, strength_small_face: 0.8,
        strength_large_face: 0.35, face_px_small: 30, face_px_large: 120,
        mask_mode: "rect", paste_region: "face_rect", feather: 24,
        colour_match: true, blend: 1, undetected_frames: "fade",
        identity_reference: "", identity_track: false, identity_threshold: 0.28,
        fallback_detector: "none", fallback_head_frac: 0.5, gamma: 1,
        denoise_smooth: 9, mask_dilation: 24, feather_scales_with_crop: false,
        sam_model: "", sam_threshold: 0.93, sam_dilation: 0, sam_temporal_smooth: 5,
    },
    audio_refine: {
        version: 1, enabled: false, room: "", reverb_enabled: true,
        reverberance: 40, hf_damping: 55, room_scale: 45, stereo_depth: 70,
        pre_delay_ms: 12, wet_gain_db: -2, normalize: false, gain_db: 0,
        use_limiter: true, sox_path: "",
    },
    preview: { enabled: true, preview_frames: 8, preview_fps: 12, max_resolution: 1024, jpeg_quality: 80, preview_every: 1 },
    save: {
        auto_save: false, reuse_first_pass: false, filename_prefix: "video/MiniMaxH3_Director",
        format: "auto", codec: "auto", encoding: "auto", crf: 23,
    },
});

const clone = (value) => JSON.parse(JSON.stringify(value));
const inChoice = (value, choices, fallback) => choices.includes(String(value || "").toLowerCase()) ? String(value || "").toLowerCase() : fallback;
// Mirrors the Python _float(): an empty or missing value falls back to the
// default, whereas Number("") would silently become 0 and clamp to the low bound.
const clampNum = (value, fallback, low, high) => {
    if (value === "" || value === null || value === undefined || typeof value === "boolean") return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.max(low, Math.min(high, parsed)) : fallback;
};

const POST_TEXT = {
    en: {
        reuse_title: "Reuse / Performance",
        global_title: "Global Refine", face_title: "Face Refine", sampling: "Second Sampling",
        upscale: "Upscale", output_resolution: "Output Resolution",
        detection_canvas: "Detection", tracking_denoise: "Refine",
        stitch: "Stitch", advanced: "Advanced Settings", enabled: "ON / OFF", disabled: "Disabled",
        detection_note: "Choose a face detector model. Lower 0.35 only when faces are missed.",
        refine_note: "Adaptive mode strengthens small faces and backs off on large faces.",
        stitch_note: "Rectangle is recommended. Use SAM only when a tighter face-shaped edge is needed.",
        no_face_detector: "No face detector model found. face_yolov8m.pt is recommended.",
        runtime_detected: "Runtime detected (validated when generation starts)",
        missing_no_downgrade: "Not installed (stage will fail without downgrade)",
        lbh_note: "Director scans compatible MiniMax H3 learned-latent checkpoints from models/latent_upscale_models automatically. Select a checkpoint below; its 2D/3D architecture is detected from the weights. No separate LBH custom node is required.",
        seedvr2_note: "SeedVR2 is a temporal-aware video upscaler. It runs on decoded frames (pixel space) and loads its own DiT + VAE model - first use downloads ~6 GB. Much crisper than latent upscalers, but slower and heavier.",
        temporal_note: "Split the upscaled video into overlapping time chunks and re-sample one chunk at a time, so sequence length no longer bounds VRAM. Chunk length and overlap snap to H3's 17-frame grid.",
        audio_title: "Audio Room",
        audio_note: "Puts generated audio in a space instead of leaving it dry on the camera mic. A scene can set its own room with a room field in the timeline; this is the fallback for scenes that do not, and the level control for all of them.",
        audio_room: "Room", audio_level: "Level", audio_advanced: "Advanced",
        audio_preset_note: "A named room sets all six values at once. Choose Custom to set them yourself.",
        audio_custom_note: "Reverb runs before level, so the tail cannot push the result into clipping.",
        audio_sox_note: "Requires SoX on PATH. Leave the path empty to auto-detect.",
        audio_final_only: "Applied once to the finished track. Segment caches stay valid.",
        export_comparison_note: "Enabling adds one extra VAE decode per segment and keeps a full-resolution raw copy in RAM for the whole run.",
        reuse_first_pass_note: "Render the base video once, then reuse its cached first pass on later runs so you can iterate on postprocess (Global Refine / Face Refine / Audio Room) without re-rendering. Overhead: one extra latent cache file per segment (disk) and it's invalidated if you change seed, prompt, refs, or resolution.",
    },
    zh: {
        reuse_title: "复用 / 性能",
        global_title: "全局精修", face_title: "人脸精修", sampling: "二次采样",
        upscale: "放大", output_resolution: "输出分辨率",
        detection_canvas: "检测", tracking_denoise: "精修",
        stitch: "回贴", advanced: "高级设置", enabled: "开 / 关", disabled: "已停用",
        detection_note: "通常只需选择人脸检测模型。置信度 0.35 可直接使用，漏脸时再降低。",
        refine_note: "自适应会加强远处小脸、减弱近处大脸，避免重写已有细节。",
        stitch_note: "推荐矩形遮罩；只有确实需要更贴脸的边缘时再使用 SAM。",
        no_face_detector: "未找到人脸检测模型，建议放入 face_yolov8m.pt。",
        runtime_detected: "已检测到运行库（生成时验证）",
        missing_no_downgrade: "未安装（此阶段会失败，不会自动降级）",
        lbh_note: "Director 会自动扫描 models/latent_upscale_models 中兼容的 MiniMax H3 Learned Latent checkpoint。只需选择模型，2D/3D 架构会直接从权重自动识别；无需另装 LBH 自定义节点。",
        seedvr2_note: "SeedVR2 是时序感知的视频放大模型，在解码后的像素空间运行，会加载自己的 DiT + VAE 模型（首次使用约下载 6 GB）。比潜变量放大更锐利，但更慢、更占资源。",
        temporal_note: "将放大后的视频切成有重叠的时间块，逐块二次采样，使序列长度不再限制显存。块长与重叠会自动对齐 H3 的 17 帧网格。",
        audio_title: "音频空间",
        audio_note: "让生成的音频带上空间感，而不是贴着脸的干声。每个片段可用时间线里的 room 字段指定自己的空间；这里是未指定时的默认值，以及所有片段的电平控制。",
        audio_room: "空间", audio_level: "电平", audio_advanced: "高级",
        audio_preset_note: "选择命名空间会一次性设定全部六个参数。选择「自定义」可自行填写。",
        audio_custom_note: "混响在电平之前处理，避免尾音把结果推到削波。",
        audio_sox_note: "需要 PATH 中存在 SoX。路径留空表示自动检测。",
        audio_final_only: "仅在成品音轨上处理一次，不会使片段缓存失效。",
        export_comparison_note: "开启后每个片段会额外解码一次 VAE，并在整个运行期间保留一份全分辨率原始副本（占用内存）。",
        reuse_first_pass_note: "先渲染一次基础版本，之后复用其缓存的首轮结果，即可在不重新渲染的情况下反复调整后处理（全局精修 / 人脸精修 / 音频空间）。代价：每个片段额外写入一份潜变量缓存（占用磁盘）；修改 seed、提示词、参考图或分辨率会使缓存失效。",
    },
};

const POST_LABELS = {
    "global_refine.denoise": ["Denoise", "降噪强度"],
    "global_refine.steps": ["Steps (0=Auto)", "步数（0=自动）"],
    "global_refine.seed_mode": ["Refine Randomness", "精修随机性"],
    "global_refine.seed_offset": ["Seed Offset", "Seed 偏移"],
    "global_refine.result_previews_enabled": ["Pass Result Previews (extra VAE decode)", "阶段结果预览（额外 VAE 解码）"],
    "global_refine.allow_refine_on_external_patch": ["Allow Refine with external attention patch", "允许外部注意力补丁时仍运行精修"],
    "global_refine.export_comparison": ["Export raw vs processed (extra VAE decode + RAM)", "导出原始与处理后对比（额外 VAE 解码 + 内存）"],
    "global_refine.skip_fl2v": ["Skip FL2V", "跳过 FL2V"],
    "global_refine.upscale_method": ["Method", "放大方法"],
    "global_refine.upscale_model": ["Model", "模型"],
    "global_refine.latent_upscale_model": ["H3 Latent Model", "H3 Latent 模型"],
    "global_refine.latent_upscale_precision": ["Precision", "精度"],
    "global_refine.latent_upscale_device": ["Device", "设备"],
    "global_refine.vsr_quality": ["VSR Quality", "VSR 质量"],
    "global_refine.resolution_mode": ["Resolution", "分辨率模式"],
    "global_refine.aspect": ["Aspect", "画幅比"],
    "global_refine.megapixels": ["Megapixels", "百万像素"],
    "global_refine.width": ["Width", "宽度"],
    "global_refine.height": ["Height", "高度"],
    "global_refine.tiled_refine": ["Tiled refine (VRAM-bound)", "分块精修（限制显存）"],
    "global_refine.tile_size": ["Tile Size", "分块尺寸"],
    "global_refine.tile_overlap": ["Tile Overlap", "分块重叠"],
    "global_refine.temporal_split": ["Temporal split (VRAM-bound)", "时间分块（限制显存）"],
    "global_refine.temporal_chunk_frames": ["Chunk Length (frames)", "块长（帧）"],
    "global_refine.temporal_overlap_frames": ["Chunk Overlap (frames)", "块重叠（帧）"],
    "save.reuse_first_pass": ["Reuse cached first pass (skip re-render)", "复用缓存的首轮结果（跳过重新渲染）"],
    "face_refine.detector": ["Detector Engine", "检测引擎"], "face_refine.detector_model": ["Face Detector Model", "人脸检测模型"],
    "face_refine.confidence": ["Confidence", "置信度"], "face_refine.select": ["Target Face", "目标人脸"],
    "face_refine.crop_factor": ["Crop Factor", "裁切倍率"], "face_refine.canvas_mode": ["Canvas Quality", "画布质量"],
    "face_refine.canvas_size": ["Canvas Size", "画布尺寸"], "face_refine.smooth_method": ["Smooth", "平滑方法"],
    "face_refine.smooth_window": ["Centre Window", "中心平滑窗口"], "face_refine.size_smooth_window": ["Size Window", "尺寸平滑窗口"],
    "face_refine.size_mode": ["Size Mode", "尺寸模式"], "face_refine.adaptive": ["Adaptive Strength", "自适应强度"],
    "face_refine.base_denoise": ["Refine Strength", "精修强度"],
    "face_refine.strength_small_face": ["Small Face", "小脸强度"],
    "face_refine.strength_large_face": ["Large Face", "大脸强度"], "face_refine.face_px_small": ["Face px Small", "小脸像素阈值"],
    "face_refine.face_px_large": ["Face px Large", "大脸像素阈值"], "face_refine.mask_mode": ["Mask", "遮罩"],
    "face_refine.paste_region": ["Paste", "回贴区域"], "face_refine.feather": ["Feather (source px)", "羽化（源画面 px）"],
    "face_refine.colour_match": ["Colour Match", "颜色匹配"], "face_refine.blend": ["Blend", "混合"],
    "face_refine.undetected_frames": ["Undetected", "未检测帧"], "face_refine.identity_reference": ["Identity Reference", "身份参考图"],
    "face_refine.identity_track": ["Identity Track", "身份跟踪"], "face_refine.identity_threshold": ["Identity Threshold", "身份阈值"],
    "face_refine.fallback_detector": ["Fallback Detector", "备用检测器"], "face_refine.fallback_head_frac": ["Fallback Head Frac", "备用头部比例"],
    "face_refine.gamma": ["Gamma", "伽马"], "face_refine.denoise_smooth": ["Denoise Smooth", "降噪平滑"],
    "face_refine.mask_dilation": ["Mask Dilation (canvas px)", "遮罩扩张（画布 px）"], "face_refine.feather_scales_with_crop": ["Legacy canvas feather", "旧式画布羽化"],
    "face_refine.sam_model": ["SAM Model", "SAM 模型"], "face_refine.sam_threshold": ["SAM Threshold", "SAM 阈值"],
    "face_refine.sam_dilation": ["SAM Dilation", "SAM 扩张"], "face_refine.sam_temporal_smooth": ["SAM Temporal", "SAM 时序平滑"],
    "audio_refine.room": ["Room", "空间"],
    "audio_refine.reverb_enabled": ["Reverb", "混响"],
    "audio_refine.reverberance": ["Reverberance %", "混响量 %"],
    "audio_refine.hf_damping": ["HF Damping %", "高频衰减 %"],
    "audio_refine.room_scale": ["Room Size %", "空间尺寸 %"],
    "audio_refine.stereo_depth": ["Stereo Depth %", "立体声深度 %"],
    "audio_refine.pre_delay_ms": ["Pre-delay (ms)", "预延迟（ms）"],
    "audio_refine.wet_gain_db": ["Wet Gain (dB)", "湿声增益（dB）"],
    "audio_refine.normalize": ["Normalize", "标准化"],
    "audio_refine.gain_db": ["Gain (dB)", "增益（dB）"],
    "audio_refine.use_limiter": ["Limiter", "限幅器"],
    "audio_refine.sox_path": ["SoX Path", "SoX 路径"],
};

const POST_OPTION_LABELS = {
    "global_refine.seed_mode": {
        inherit: ["Keep original Seed (recommended)", "保持原 Seed（推荐）"],
        offset: ["Use Seed offset", "使用 Seed 偏移"],
    },
    "global_refine.upscale_method": {
        lanczos: ["Lanczos", "Lanczos"], upscale_model: ["Upscale Model", "放大模型"],
        nvidia_rtx_vsr: ["NVIDIA RTX VSR", "NVIDIA RTX VSR"],
        h3_learned_latent: ["H3 Learned Latent", "H3 Learned Latent"],
        seedvr2: ["SeedVR2 (video)", "SeedVR2（视频）"],
    },
    "global_refine.latent_upscale_precision": { fp16: ["FP16", "FP16"], bf16: ["BF16", "BF16"], fp32: ["FP32", "FP32"] },
    "global_refine.latent_upscale_device": { cuda: ["CUDA", "CUDA"], cpu: ["CPU", "CPU"] },
    "global_refine.vsr_quality": {
        low: ["Low", "Low"], medium: ["Medium", "Medium"], high: ["High", "High"], ultra: ["Ultra", "Ultra"],
    },
    "global_refine.resolution_mode": {
        follow_director: ["Follow Director", "跟随 Director"],
        aspect_megapixels: ["Aspect + Megapixels", "画幅比 + 百万像素"], custom: ["Custom", "自定义"],
    },
    "face_refine.select": { largest: ["Largest", "最大脸"], most_central: ["Most central", "最靠近中心"] },
    "face_refine.canvas_mode": {
        manual: ["Manual", "手动"], auto_no_downscale: ["Preserve source detail", "保留原始细节"],
        auto_capped_768: ["Auto (recommended, max 768)", "自动（推荐，上限 768）"],
    },
    "face_refine.smooth_method": {
        gaussian: ["Gaussian", "高斯"], savgol: ["Savitzky–Golay", "Savitzky–Golay"],
        moving_average: ["Moving average", "移动平均"],
    },
    "face_refine.size_mode": { adaptive: ["Adaptive", "自适应"], stable: ["Stable", "稳定"] },
    "face_refine.mask_mode": { rect: ["Rectangle (recommended)", "矩形（推荐）"], ellipse: ["Ellipse", "椭圆"], sam: ["SAM (optional)", "SAM（可选）"] },
    "face_refine.paste_region": { face_rect: ["Face rectangle", "人脸区域"], full_crop: ["Full crop", "完整裁切区"] },
    "face_refine.undetected_frames": { fade: ["Fade", "淡出"], skip: ["Skip", "跳过"] },
    "face_refine.fallback_detector": { none: ["None", "无"] },
    "audio_refine.room": {
        "": ["Custom (six values below)", "自定义（下方六个参数）"],
        dry: ["Dry / studio (no space)", "干声 / 录音棚（无空间）"],
        bedroom: ["Bedroom (soft, damped)", "卧室（柔软吸音）"],
        bathroom: ["Bathroom (tiled, bright)", "浴室（瓷砖，明亮）"],
        bar: ["Bar / tavern", "酒吧 / 酒馆"],
        office: ["Office / kitchen", "办公室 / 厨房"],
        car: ["Car interior", "车内"],
        hall: ["Hall / warehouse", "大厅 / 仓库"],
        cathedral: ["Cathedral / church", "教堂"],
        outdoor: ["Outdoor / open air", "室外 / 开阔地"],
    },
};

export function normalizePostprocessConfig(raw) {
    if (typeof raw === "string") {
        try { raw = raw.trim() ? JSON.parse(raw) : {}; } catch { raw = {}; }
    }
    raw = raw && typeof raw === "object" ? raw : {};
    const result = clone(DEFAULT_CONFIG);
    for (const key of ["global_refine", "face_refine", "audio_refine", "preview", "save"]) {
        const legacy = { global_refine: raw.globalRefine, face_refine: raw.faceRefine, audio_refine: raw.audioRefine }[key] || null;
        Object.assign(result[key], legacy || {}, raw[key] || {});
    }
    if (raw.liveTaePreview === false || raw.live_tae_preview === false) result.preview.enabled = false;
    const rawVersion=Number(raw.version||0);
    if(rawVersion>0&&rawVersion<4){
        const m={crop_factor:[2,2.5],smooth_window:[9,21],size_smooth_window:[13,51],base_denoise:[0.22,0.45],strength_small_face:[0.35,0.8],strength_large_face:[0.16,0.35],face_px_small:[96,30],face_px_large:[320,120],feather:[0.12,24],identity_threshold:[0.35,0.28],fallback_head_frac:[0.34,0.5],denoise_smooth:[5,9],mask_dilation:[0.06,24],feather_scales_with_crop:[true,false],sam_threshold:[0.5,0.93],sam_dilation:[0.04,0]};
        for(const [k,[a,b]] of Object.entries(m)) if(result.face_refine[k]===a) result.face_refine[k]=b;
    }
    const global = result.global_refine;
    global.enabled = !!global.enabled;
    global.mode = inChoice(global.mode, ["refine", "upscale"], "refine");
    global.second_sampling_enabled = global.second_sampling_enabled !== false;
    global.result_previews_enabled = global.result_previews_enabled === true;
    global.allow_refine_on_external_patch = global.allow_refine_on_external_patch === true;
    global.export_comparison = global.export_comparison === true;
    global.seed_mode = inChoice(global.seed_mode, ["inherit", "offset"], "inherit");
    const seedOffset = Number(global.seed_offset);
    global.seed_offset = Number.isFinite(seedOffset)
        ? Math.max(-2147483648, Math.min(2147483647, Math.trunc(seedOffset)))
        : 1;
    global.upscale_method = inChoice(global.upscale_method, ["lanczos", "upscale_model", "nvidia_rtx_vsr", "h3_learned_latent", "seedvr2"], "lanczos");
    global.latent_upscale_model = String(global.latent_upscale_model || "").trim();
    delete global.latent_upscale_variant;
    global.latent_upscale_precision = inChoice(global.latent_upscale_precision, ["fp16", "bf16", "fp32"], "fp16");
    global.latent_upscale_device = inChoice(global.latent_upscale_device, ["cuda", "cpu"], "cuda");
    global.vsr_quality = inChoice(global.vsr_quality, ["low", "medium", "high", "ultra"], "high");
    global.resolution_mode = inChoice(global.resolution_mode, ["follow_director", "aspect_megapixels", "custom"], "follow_director");
    global.rtx_deblur_enabled = !!global.rtx_deblur_enabled;
    global.rtx_deblur_quality = inChoice(global.rtx_deblur_quality, ["low", "medium", "high", "ultra"], "medium");
    const deblurStrength = Number(global.rtx_deblur_strength);
    global.rtx_deblur_strength = Number.isFinite(deblurStrength) ? Math.max(0, Math.min(3, deblurStrength)) : 1;
    global.tiled_refine = !!global.tiled_refine;
    global.tile_size = Math.max(256, Math.min(2048, Math.round(Number(global.tile_size || 512) / 32) * 32 || 512));
    global.tile_overlap = Math.max(0, Math.min(512, Math.round(Number(global.tile_overlap || 96) / 32) * 32 || 96));
    global.temporal_split = !!global.temporal_split;
    global.temporal_chunk_frames = Math.max(17, Math.min(4096, Math.round(Number(global.temporal_chunk_frames || 136) / 17) * 17 || 136));
    global.temporal_overlap_frames = Math.max(0, Math.min(512, Math.round(Number(global.temporal_overlap_frames || 17) / 17) * 17 || 17));
    const face=result.face_refine;
    face.enabled=!!face.enabled;
    face.detector=inChoice(face.detector,["ultralytics","insightface"],"ultralytics");
    face.select=inChoice(face.select,["largest","most_central"],"largest");
    face.canvas_mode=inChoice(face.canvas_mode,["manual","auto_no_downscale","auto_capped_768"],"auto_capped_768");
    face.smooth_method=inChoice(face.smooth_method,["gaussian","savgol","moving_average"],"gaussian");
    face.size_mode=inChoice(face.size_mode,["adaptive","stable"],"adaptive");
    face.mask_mode=inChoice(face.mask_mode,["rect","ellipse","sam"],"rect");
    face.paste_region=inChoice(face.paste_region,["face_rect","full_crop"],"face_rect");
    face.undetected_frames=inChoice(face.undetected_frames,["fade","skip"],"fade");
    face.adaptive=face.adaptive!==false;
    face.identity_track=!!face.identity_track;
    face.feather_scales_with_crop=!!face.feather_scales_with_crop;
    const audio=result.audio_refine;
    audio.enabled=!!audio.enabled;
    audio.reverb_enabled=audio.reverb_enabled!==false;
    // An empty room means "no opinion": the six explicit values below apply.
    audio.room=ROOM_NAMES.includes(String(audio.room||"").trim().toLowerCase())?String(audio.room).trim().toLowerCase():"";
    audio.reverberance=clampNum(audio.reverberance,40,0,100);
    audio.hf_damping=clampNum(audio.hf_damping,55,0,100);
    audio.room_scale=clampNum(audio.room_scale,45,0,100);
    audio.stereo_depth=clampNum(audio.stereo_depth,70,0,100);
    audio.pre_delay_ms=clampNum(audio.pre_delay_ms,12,0,500);
    audio.wet_gain_db=clampNum(audio.wet_gain_db,-2,-10,10);
    audio.normalize=!!audio.normalize;
    audio.gain_db=clampNum(audio.gain_db,0,-20,20);
    audio.use_limiter=audio.use_limiter!==false;
    audio.sox_path=String(audio.sox_path||"").trim().slice(0,2048);
    result.preview.enabled = result.preview.enabled !== false;
    result.save.auto_save = !!result.save.auto_save;
    result.save.reuse_first_pass = !!result.save.reuse_first_pass;
    result.save.filename_prefix = String(result.save.filename_prefix || "video/MiniMaxH3_Director").trim().slice(0, 512) || "video/MiniMaxH3_Director";
    result.save.format = String(result.save.format || "auto").trim().toLowerCase().slice(0, 32) || "auto";
    result.save.codec = String(result.save.codec || "auto").trim().toLowerCase().slice(0, 64) || "auto";
    result.save.encoding = result.save.encoding === "re-encode" ? "re-encode" : "auto";
    result.save.crf = Math.max(0, Math.min(51, Math.round(Number(result.save.crf) || 23)));
    result.version = 11;
    return result;
}

export function serializePostprocessConfig(raw) {
    return JSON.stringify(normalizePostprocessConfig(raw));
}

function snap(value) { return Math.max(32, Math.round(Number(value || 32) / 32) * 32); }

export function resolveGlobalTarget(config, directorWidth = 864, directorHeight = 480) {
    const global = normalizePostprocessConfig(config).global_refine;
    if (global.resolution_mode === "follow_director") return [snap(directorWidth), snap(directorHeight)];
    if (global.resolution_mode === "custom") return [snap(global.width), snap(global.height)];
    const match = String(global.aspect || "16:9").match(/^(\d+):(\d+)$/);
    const aw = Number(match?.[1] || 16), ah = Number(match?.[2] || 9);
    const scale = Math.sqrt(Math.max(0.1, Number(global.megapixels || 1)) * 1024 * 1024 / (aw * ah));
    return [snap(aw * scale), snap(ah * scale)];
}

export function setGlobalUpscaleEnabled(config, enabled) {
    const next = normalizePostprocessConfig(config);
    next.global_refine.mode = enabled ? "upscale" : "refine";
    return next;
}

export function globalRefineVisibility(config) {
    const global = normalizePostprocessConfig(config).global_refine;
    const upscaleEnabled = global.mode === "upscale";
    return {
        secondSampling: global.second_sampling_enabled,
        upscaleEnabled,
        seedOffset: global.second_sampling_enabled && global.seed_mode === "offset",
        tiled: global.second_sampling_enabled && global.tiled_refine,
        temporal: global.second_sampling_enabled && global.temporal_split,
        upscaleModel: upscaleEnabled && global.upscale_method === "upscale_model",
        learnedLatent: upscaleEnabled && global.upscale_method === "h3_learned_latent",
        vsr: upscaleEnabled && global.upscale_method === "nvidia_rtx_vsr",
        seedvr2: upscaleEnabled && global.upscale_method === "seedvr2",
        aspectMegapixels: upscaleEnabled && global.resolution_mode === "aspect_megapixels",
        customSize: upscaleEnabled && global.resolution_mode === "custom",
    };
}

export function faceRefineVisibility(config){
    const f=normalizePostprocessConfig(config).face_refine;
    return {detectorModel:f.detector==="ultralytics",manualCanvas:f.canvas_mode==="manual",sam:f.mask_mode==="sam",identity:!!f.identity_track,fallback:String(f.fallback_detector||"none")!=="none"};
}

export function globalRefineSummary(config, width = 864, height = 480, locale = "en") {
    const global = normalizePostprocessConfig(config).global_refine;
    const zh = locale === "zh";
    if (!global.enabled) return POST_TEXT[zh ? "zh" : "en"].disabled;
    const parts = [];
    if (global.second_sampling_enabled) {
        const steps = Number(global.steps) > 0 ? `${global.steps} ${zh ? "步" : "Steps"}` : (zh ? "自动步数" : "Auto Steps");
        const seed = global.seed_mode === "offset"
            ? `${zh ? "Seed 偏移" : "Seed Offset"} ${Number(global.seed_offset) >= 0 ? "+" : ""}${Number(global.seed_offset)}`
            : (zh ? "保持原 Seed" : "Keep original Seed");
        parts.push(zh ? "二次采样 ON" : "Second Sampling ON", `D${Number(global.denoise).toFixed(2)}`, steps, seed);
        if (global.result_previews_enabled) parts.push(zh ? "阶段预览 ON" : "Pass Previews ON");
    } else {
        parts.push(zh ? "二次采样 OFF" : "Second Sampling OFF");
    }
    if (global.export_comparison) parts.push(zh ? "导出对比 ON" : "Compare Export ON");
    if (global.mode === "upscale") {
        const [targetW, targetH] = resolveGlobalTarget(config, width, height);
        let method = global.upscale_method === "upscale_model" ? (global.upscale_model || (zh ? "放大模型" : "Upscale Model")) : "Lanczos";
        if (global.upscale_method === "nvidia_rtx_vsr") {
            const quality = String(global.vsr_quality || "high");
            method = `RTX VSR ${quality.charAt(0).toUpperCase()}${quality.slice(1)}`;
        } else if (global.upscale_method === "h3_learned_latent") {
            method = "H3 Learned Latent";
        } else if (global.upscale_method === "seedvr2") {
            method = "SeedVR2";
        }
        parts.push(`${method} → ${targetW}×${targetH}`);
    }
    return parts.join(" · ");
}

export function faceRefineSummary(config, locale = "en") {
    const face = normalizePostprocessConfig(config).face_refine;
    const zh = locale === "zh";
    if (!face.enabled) return POST_TEXT[zh ? "zh" : "en"].disabled;
    const canvas=face.canvas_mode==="manual"?`${face.canvas_size}`:face.canvas_mode==="auto_capped_768"?(zh?"自动 768":"Auto 768"):(zh?"保留细节":"Preserve detail");
    const target=face.select==="most_central"?(zh?"中心脸":"Central face"):(zh?"最大脸":"Largest face");
    const strength=`${face.adaptive?(zh?"自适应":"Adaptive"):(zh?"固定":"Fixed")} D${Number(face.base_denoise).toFixed(2)}`;
    const mask=face.mask_mode==="sam"?"SAM":face.mask_mode==="ellipse"?(zh?"椭圆":"Ellipse"):(zh?"矩形":"Rect");
    return `${target} · ${canvas} · ${strength} · ${mask}`;
}

export function audioRefineVisibility(config) {
    const audio = normalizePostprocessConfig(config).audio_refine;
    return {
        // A named room supplies all six values, so the manual fields are hidden
        // exactly when a preset is selected.  Reverb off hides them too.
        customRoom: audio.reverb_enabled && !audio.room,
        limiter: Number(audio.gain_db) > 0,
    };
}

export function audioRefineSummary(config, locale = "en") {
    const audio = normalizePostprocessConfig(config).audio_refine;
    const zh = locale === "zh";
    if (!audio.enabled) return POST_TEXT[zh ? "zh" : "en"].disabled;
    const parts = [];
    if (audio.reverb_enabled) {
        const short = ROOM_SHORT[audio.room];
        parts.push(short ? short[zh ? 1 : 0] : zh ? "自定义空间" : "Custom room");
        if (!audio.room) {
            parts.push(`${zh ? "混响" : "Rev"} ${Math.round(audio.reverberance)}%`, `${zh ? "尺寸" : "Size"} ${Math.round(audio.room_scale)}%`);
        }
    } else {
        parts.push(zh ? "无混响" : "No reverb");
    }
    if (audio.normalize) parts.push(zh ? "标准化" : "Normalize");
    const gain = Number(audio.gain_db);
    if (Math.abs(gain) >= 0.01) parts.push(`${gain >= 0 ? "+" : ""}${gain} dB`);
    return parts.join(" · ");
}

export class PostprocessConfigStore {
    constructor(widget, { onChange } = {}) {
        this.widget = widget;
        this.onChange = onChange;
        this.listeners = new Set();
        this.value = normalizePostprocessConfig(widget?.value);
    }
    get() { return clone(this.value); }
    set(next, { notify = true } = {}) {
        this.value = normalizePostprocessConfig(next);
        const serialized = serializePostprocessConfig(this.value);
        if (this.widget) {
            this.widget.value = serialized;
            try {
                this.widget.callback?.(serialized);
            } catch (error) {
                console.warn("[MiniMax H3 Motion Director] postprocess widget callback failed:", error);
            }
        }
        if (notify) {
            try { this.onChange?.(this.get()); }
            catch (error) { console.warn("[MiniMax H3 Motion Director] postprocess onChange failed:", error); }
            this.listeners.forEach((listener) => {
                try { listener(this.get()); }
                catch (error) { console.warn("[MiniMax H3 Motion Director] postprocess listener failed:", error); }
            });
        }
        return this.get();
    }
    patch(section, key, value) {
        const next = this.get();
        next[section][key] = value;
        return this.set(next);
    }
    toggle(section) { return this.patch(section, "enabled", !this.value[section].enabled); }
    subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
    reload() {
        this.value = normalizePostprocessConfig(this.widget?.value);
        this.listeners.forEach((fn) => {
            try { fn(this.get()); }
            catch (error) { console.warn("[MiniMax H3 Motion Director] postprocess reload listener failed:", error); }
        });
    }
}

const STYLE_ID = "mmx-postprocess-styles";
function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.mmx-postprocess-page{display:flex;flex-direction:column;gap:8px;height:100%;min-height:0;box-sizing:border-box}
.mmx-post-reuse-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid #343434;border-radius:8px;background:#181818;padding:6px 10px;flex:0 0 auto;box-sizing:border-box}
.mmx-post-reuse-title{margin:0;font-size:13px;color:#ddd;white-space:nowrap}
.mmx-post-reuse-check{display:flex;align-items:center;gap:6px;font-size:12px;color:#aaa;white-space:nowrap}
.mmx-post-reuse-note{margin:0;color:#aaa;font-size:12px;line-height:1.45;flex:1 1 260px;min-width:220px}
.mmx-post-reuse-bar .mmx-post-note{font-size:12px;line-height:1.45;color:#aaa}
.mmx-postprocess{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;flex:1 1 auto;min-height:0;box-sizing:border-box}
.mmx-post-column{min-width:0;overflow:auto;border:1px solid #343434;border-radius:8px;background:#181818;padding:10px;box-sizing:border-box}
.mmx-post-head,.mmx-post-section-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.mmx-post-head{margin-bottom:8px}.mmx-post-head h3{margin:0;font-size:15px}
.mmx-post-section-head h4{margin:0;font-size:12px;color:#ddd}.mmx-post-enable,.mmx-post-subenable{display:flex;align-items:center;gap:6px;color:#4fff8f;font-weight:650}
.mmx-post-summary{min-height:18px;margin:0 0 8px;color:#aaa;font-size:11px}.mmx-post-note{margin:0 0 7px;color:#888;font-size:10px;line-height:1.45}
.mmx-post-section{margin:7px 0;padding:7px;border:1px solid #2d2d2d;border-radius:6px;background:#1d1d1d}.mmx-post-section>h4{margin:0 0 6px;font-size:12px;color:#ddd}
.mmx-post-section-body{margin-top:7px}.mmx-post-divider-title{margin:10px 0 6px;padding-top:8px;border-top:1px solid #303030;font-size:11px;font-weight:650;color:#bbb}
.mmx-post-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px 8px}.mmx-post-field{display:grid;grid-template-columns:minmax(82px,.9fr) minmax(0,1.2fr);align-items:center;gap:6px;min-width:0;font-size:11px;color:#aaa}
.mmx-post-field input,.mmx-post-field select{min-width:0;width:100%;height:26px;border:1px solid #3b3b3b;border-radius:4px;background:#242424;color:#ddd;padding:2px 5px;box-sizing:border-box}
.mmx-post-field input[type=checkbox]{width:auto;height:auto;justify-self:start}.mmx-post-wide{grid-column:1/-1}.mmx-post-conditional{min-width:0}.mmx-post-conditional[hidden],.mmx-post-section-body[hidden]{display:none!important}
.mmx-post-result{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:5px 7px;border-radius:4px;background:#202020}.mmx-post-result b{color:#ddd;font-size:12px}
.mmx-post-advanced>summary{cursor:pointer;color:#bbb;font-size:12px;font-weight:650;padding:3px}
.mmx-post-disabled{opacity:.52}.mmx-post-capability{font-size:10px;color:#999}.mmx-post-capability.bad{color:#ff8d8d}
@media(max-width:980px){.mmx-postprocess{grid-template-columns:1fr}.mmx-post-column{overflow:visible}.mmx-post-grid{grid-template-columns:1fr}}
`;
    document.head.appendChild(style);
}

function options(rows) { return rows.map(([value, label]) => `<option value="${value}">${label}</option>`).join(""); }
function field(label, path, type = "number", extra = "") {
    if (type === "select") return `<label class="mmx-post-field"><span data-field-label="${path}">${label}</span><select data-path="${path}">${extra}</select></label>`;
    if (type === "checkbox") return `<label class="mmx-post-field"><span data-field-label="${path}">${label}</span><input type="checkbox" data-path="${path}"></label>`;
    return `<label class="mmx-post-field"><span data-field-label="${path}">${label}</span><input type="${type}" data-path="${path}" ${extra}></label>`;
}
function conditional(name, content) { return `<div class="mmx-post-conditional" data-conditional="${name}">${content}</div>`; }

export function mountPostprocessUI(container, store, { fetchApi, directorSize = () => [864, 480], locale = () => "zh" } = {}) {
    ensureStyles();
    const root = document.createElement("div");
    root.className = "mmx-postprocess-page";
    root.innerHTML = `
      <div class="mmx-post-reuse-bar">
        <h3 class="mmx-post-reuse-title" data-post-text="reuse_title">Reuse / Performance</h3>
        <label class="mmx-post-reuse-check"><span data-field-label="save.reuse_first_pass">Reuse cached first pass (skip re-render)</span><input type="checkbox" data-path="save.reuse_first_pass"></label>
        <p class="mmx-post-note mmx-post-reuse-note" data-post-text="reuse_first_pass_note"></p>
      </div>
      <div class="mmx-postprocess">
      <section class="mmx-post-column" data-section="global_refine">
        <div class="mmx-post-head"><h3 data-post-text="global_title">全局精修</h3><label class="mmx-post-enable"><input type="checkbox" data-path="global_refine.enabled"> <span data-post-text="enabled">ON / OFF</span></label></div>
        <p class="mmx-post-summary" data-summary="global_refine"></p>
        <div class="mmx-post-section" data-second-sampling-section>
          <div class="mmx-post-section-head"><h4 data-post-text="sampling">二次采样</h4><label class="mmx-post-subenable"><input type="checkbox" data-path="global_refine.second_sampling_enabled"> <span data-post-text="enabled">ON / OFF</span></label></div>
          <div class="mmx-post-section-body" data-second-sampling-body><div class="mmx-post-grid">
            ${field("Denoise", "global_refine.denoise", "number", 'min="0.01" max="1" step="0.01"')}
            ${field("Steps (0=Auto)", "global_refine.steps", "number", 'min="0" max="200" step="1"')}
            ${field("Refine Randomness", "global_refine.seed_mode", "select", options([["inherit","Keep original Seed (recommended)"],["offset","Use Seed offset"]]))}
            ${conditional("seed_offset", field("Seed Offset", "global_refine.seed_offset", "number", 'min="-2147483648" max="2147483647" step="1"'))}
            ${field("Pass Result Previews (extra VAE decode)", "global_refine.result_previews_enabled", "checkbox")}
            ${field("Skip FL2V", "global_refine.skip_fl2v", "checkbox")}
            ${field("Allow Refine with external attention patch", "global_refine.allow_refine_on_external_patch", "checkbox")}
            ${field("Export raw vs processed (extra VAE decode)", "global_refine.export_comparison", "checkbox")}
            <p class="mmx-post-note mmx-post-wide" data-post-text="export_comparison_note"></p>
            ${field("Tiled refine (VRAM-bound)", "global_refine.tiled_refine", "checkbox")}
            ${conditional("tiled", field("Tile Size", "global_refine.tile_size", "number", 'min="256" max="2048" step="32"'))}
            ${conditional("tiled", field("Tile Overlap", "global_refine.tile_overlap", "number", 'min="0" max="512" step="32"'))}
            ${field("Temporal split (VRAM-bound)", "global_refine.temporal_split", "checkbox")}
            ${conditional("temporal", field("Chunk Length (frames)", "global_refine.temporal_chunk_frames", "number", 'min="17" max="4096" step="17"'))}
            ${conditional("temporal", field("Chunk Overlap (frames)", "global_refine.temporal_overlap_frames", "number", 'min="0" max="512" step="17"'))}
            <p class="mmx-post-note mmx-post-wide" data-conditional="temporal" data-post-text="temporal_note"></p>
          </div></div>
        </div>
        <div class="mmx-post-section" data-upscale-section>
          <div class="mmx-post-section-head"><h4 data-post-text="upscale">Upscale</h4><label class="mmx-post-subenable"><input type="checkbox" data-upscale-enabled> <span data-post-text="enabled">ON / OFF</span></label></div>
          <div class="mmx-post-section-body" data-upscale-body>
            <div class="mmx-post-grid">
              ${field("Method", "global_refine.upscale_method", "select", options([["lanczos","Lanczos"],["upscale_model","Upscale Model (Real-ESRGAN etc.)"],["nvidia_rtx_vsr","NVIDIA RTX VSR"],["h3_learned_latent","H3 Learned Latent"],["seedvr2","SeedVR2 (video)"]]))}
              ${conditional("upscale_model", field("Model", "global_refine.upscale_model", "select", '<option value="">—</option>'))}
              ${conditional("learned_latent", field("H3 Latent Model", "global_refine.latent_upscale_model", "select", '<option value="">—</option>'))}
              ${conditional("learned_latent", field("Precision", "global_refine.latent_upscale_precision", "select", options([["fp16","FP16"],["bf16","BF16"],["fp32","FP32"]])))}
              ${conditional("learned_latent", field("Device", "global_refine.latent_upscale_device", "select", options([["cuda","CUDA"],["cpu","CPU"]])))}
              <p class="mmx-post-note mmx-post-wide" data-conditional="learned_latent" data-post-text="lbh_note"></p>
              ${conditional("vsr_quality", field("VSR Quality", "global_refine.vsr_quality", "select", options([["low","Low"],["medium","Medium"],["high","High"],["ultra","Ultra"]])))}
              <div class="mmx-post-capability mmx-post-wide" data-conditional="vsr_status" data-capability="nvidia_rtx_vsr"></div>
              <p class="mmx-post-note mmx-post-wide" data-conditional="seedvr2" data-post-text="seedvr2_note"></p>
            </div>
            <div class="mmx-post-divider-title" data-post-text="output_resolution">Output Resolution</div>
            <div class="mmx-post-grid">
              ${field("Resolution", "global_refine.resolution_mode", "select", options([["follow_director","Follow Director"],["aspect_megapixels","Aspect + Megapixels"],["custom","Custom"]]))}
              ${conditional("aspect", field("Aspect", "global_refine.aspect", "select", options([["1:1","1:1"],["4:3","4:3"],["3:4","3:4"],["16:9","16:9"],["9:16","9:16"],["21:9","21:9"]])))}
              ${conditional("megapixels", field("Megapixels", "global_refine.megapixels", "number", 'min="0.1" max="16" step="0.1"'))}
              ${conditional("width", field("Width", "global_refine.width", "number", 'min="32" max="8192" step="32"'))}
              ${conditional("height", field("Height", "global_refine.height", "number", 'min="32" max="8192" step="32"'))}
              <div class="mmx-post-result mmx-post-wide"><span data-field-label="resolved_target">Resolved Target</span><b data-resolved-target></b></div>
            </div>
          </div>
        </div>
      </section>
      <section class="mmx-post-column" data-section="face_refine">
        <div class="mmx-post-head"><h3 data-post-text="face_title">Face Refine</h3><label class="mmx-post-enable"><input type="checkbox" data-path="face_refine.enabled"> <span data-post-text="enabled">ON / OFF</span></label></div>
        <p class="mmx-post-summary" data-summary="face_refine"></p>
        <div class="mmx-post-section"><h4 data-post-text="detection_canvas">Detection</h4><p class="mmx-post-note" data-post-text="detection_note"></p><div class="mmx-post-grid">
          ${conditional("face_detector_model", field("Face Detector Model", "face_refine.detector_model", "select", '<option value="">—</option>'))}
          ${field("Confidence", "face_refine.confidence", "number", 'min="0.05" max="0.95" step="0.05"')}
          ${field("Target Face", "face_refine.select", "select", options([["largest","largest"],["most_central","most_central"]]))}
          <div class="mmx-post-capability mmx-post-wide" data-capability="face_detector"></div>
        </div></div>
        <div class="mmx-post-section"><h4 data-post-text="tracking_denoise">Refine</h4><p class="mmx-post-note" data-post-text="refine_note"></p><div class="mmx-post-grid">
          ${field("Adaptive Strength", "face_refine.adaptive", "checkbox")}
          ${field("Refine Strength", "face_refine.base_denoise", "number", 'min="0.01" max="1" step="0.01"')}
          ${field("Canvas Quality", "face_refine.canvas_mode", "select", options([["auto_capped_768","Auto (recommended, max 768)"],["auto_no_downscale","Preserve source detail"],["manual","Manual"]]))}
          ${conditional("face_canvas_size", field("Canvas Size", "face_refine.canvas_size", "number", 'min="256" max="1536" step="32"'))}
        </div></div>
        <div class="mmx-post-section"><h4 data-post-text="stitch">Stitch</h4><p class="mmx-post-note" data-post-text="stitch_note"></p><div class="mmx-post-grid">
          ${field("Mask", "face_refine.mask_mode", "select", options([["rect","Rectangle (recommended)"],["ellipse","Ellipse"],["sam","SAM (optional)"]]))}
          ${conditional("face_sam_model", field("SAM Model", "face_refine.sam_model", "select", '<option value="">—</option>'))}
          ${field("Colour Match", "face_refine.colour_match", "checkbox")}
          ${field("Blend", "face_refine.blend", "number", 'min="0" max="1" step="0.05"')}
        </div></div>
        <details class="mmx-post-section mmx-post-advanced"><summary data-post-text="advanced">Advanced Settings</summary>
          <div class="mmx-post-divider-title">Tracking</div><div class="mmx-post-grid">
            ${field("Detector Engine", "face_refine.detector", "select", options([["ultralytics","YOLO"],["insightface","InsightFace"]]))}
            ${field("Crop Factor", "face_refine.crop_factor", "number", 'min="1.2" max="5" step="0.1"')}
            ${field("Smooth", "face_refine.smooth_method", "select", options([["gaussian","gaussian"],["savgol","savgol"],["moving_average","moving_average"]]))}
            ${field("Centre Window", "face_refine.smooth_window", "number", 'min="1" max="201" step="2"')}
            ${field("Size Window", "face_refine.size_smooth_window", "number", 'min="1" max="201" step="2"')}
            ${field("Size Mode", "face_refine.size_mode", "select", options([["adaptive","adaptive"],["stable","stable"]]))}
          </div>
          <div class="mmx-post-divider-title">Adaptive Denoise</div><div class="mmx-post-grid">
            ${field("Small Face", "face_refine.strength_small_face", "number", 'min="0" max="1" step="0.05"')}
            ${field("Large Face", "face_refine.strength_large_face", "number", 'min="0" max="1" step="0.05"')}
            ${field("Face px Small", "face_refine.face_px_small", "number", 'min="4" max="400" step="1"')}
            ${field("Face px Large", "face_refine.face_px_large", "number", 'min="8" max="800" step="1"')}
            ${field("Gamma", "face_refine.gamma", "number", 'min="0.1" max="4" step="0.1"')}
            ${field("Denoise Smooth", "face_refine.denoise_smooth", "number", 'min="1" max="51" step="2"')}
          </div>
          <div class="mmx-post-divider-title">Identity / Fallback</div><div class="mmx-post-grid">
            ${field("Identity Track", "face_refine.identity_track", "checkbox")}
            ${conditional("face_identity", field("Identity Reference", "face_refine.identity_reference", "text"))}
            ${conditional("face_identity", field("Identity Threshold", "face_refine.identity_threshold", "number", 'min="0" max="1" step="0.01"'))}
            ${field("Fallback Detector", "face_refine.fallback_detector", "select", options([["none","none"]]))}
            ${conditional("face_fallback", field("Fallback Head Frac", "face_refine.fallback_head_frac", "number", 'min="0" max="1.5" step="0.05"'))}
          </div>
          <div class="mmx-post-divider-title">Stitch</div><div class="mmx-post-grid">
            ${field("Paste", "face_refine.paste_region", "select", options([["face_rect","face_rect"],["full_crop","full_crop"]]))}
            ${field("Feather", "face_refine.feather", "number", 'min="0" max="256" step="2"')}
            ${field("Mask Dilation", "face_refine.mask_dilation", "number", 'min="0" max="256" step="2"')}
            ${field("Undetected", "face_refine.undetected_frames", "select", options([["fade","fade"],["skip","skip"]]))}
            ${field("Legacy canvas feather", "face_refine.feather_scales_with_crop", "checkbox")}
          </div>
          <div class="mmx-post-divider-title">SAM</div><div class="mmx-post-grid">
            ${conditional("face_sam_advanced", field("SAM Threshold", "face_refine.sam_threshold", "number", 'min="0" max="1" step="0.01"'))}
            ${conditional("face_sam_advanced", field("SAM Dilation", "face_refine.sam_dilation", "number", 'min="0" max="256" step="1"'))}
            ${conditional("face_sam_advanced", field("SAM Temporal", "face_refine.sam_temporal_smooth", "number", 'min="1" max="51" step="2"'))}
          </div>
        </details>
      </section>
      <section class="mmx-post-column" data-section="audio_refine">
        <div class="mmx-post-head"><h3 data-post-text="audio_title">Audio Room</h3><label class="mmx-post-enable"><input type="checkbox" data-path="audio_refine.enabled"> <span data-post-text="enabled">ON / OFF</span></label></div>
        <p class="mmx-post-summary" data-summary="audio_refine"></p>
        <p class="mmx-post-note" data-post-text="audio_note"></p>
        <div class="mmx-post-section"><h4 data-post-text="audio_room">Room</h4><p class="mmx-post-note" data-post-text="audio_preset_note"></p><div class="mmx-post-grid">
          ${field("Room", "audio_refine.room", "select", options([["","Custom (six values below)"],["dry","Dry / studio (no space)"],["bedroom","Bedroom (soft, damped)"],["bathroom","Bathroom (tiled, bright)"],["bar","Bar / tavern"],["office","Office / kitchen"],["car","Car interior"],["hall","Hall / warehouse"],["cathedral","Cathedral / church"],["outdoor","Outdoor / open air"]]))}
          ${field("Reverb", "audio_refine.reverb_enabled", "checkbox")}
          ${conditional("audio_custom", field("Reverberance %", "audio_refine.reverberance", "number", 'min="0" max="100" step="1"'))}
          ${conditional("audio_custom", field("HF Damping %", "audio_refine.hf_damping", "number", 'min="0" max="100" step="1"'))}
          ${conditional("audio_custom", field("Room Size %", "audio_refine.room_scale", "number", 'min="0" max="100" step="1"'))}
          ${conditional("audio_custom", field("Stereo Depth %", "audio_refine.stereo_depth", "number", 'min="0" max="100" step="1"'))}
          ${conditional("audio_custom", field("Pre-delay (ms)", "audio_refine.pre_delay_ms", "number", 'min="0" max="500" step="1"'))}
          ${conditional("audio_custom", field("Wet Gain (dB)", "audio_refine.wet_gain_db", "number", 'min="-10" max="10" step="0.5"'))}
          ${conditional("audio_custom", '<p class="mmx-post-note mmx-post-wide" data-post-text="audio_custom_note"></p>')}
        </div></div>
        <div class="mmx-post-section"><h4 data-post-text="audio_level">Level</h4><div class="mmx-post-grid">
          ${field("Normalize", "audio_refine.normalize", "checkbox")}
          ${field("Gain (dB)", "audio_refine.gain_db", "number", 'min="-20" max="20" step="0.5"')}
        </div></div>
        <details class="mmx-post-section mmx-post-advanced"><summary data-post-text="audio_advanced">Advanced</summary>
          <p class="mmx-post-note" data-post-text="audio_sox_note"></p><div class="mmx-post-grid">
            ${field("Limiter", "audio_refine.use_limiter", "checkbox")}
            ${field("SoX Path", "audio_refine.sox_path", "text")}
          </div>
          <p class="mmx-post-note" data-post-text="audio_final_only"></p>
        </details>
      </section>
      </div>`;
    container.replaceChildren(root);

    // An emptied number field must stay "" so normalize can apply that field's
    // default.  Number("") is 0, which would silently clamp to the minimum.
    const readInput = (element) => element.type === "checkbox" ? element.checked
        : element.type === "number" ? (element.value === "" ? "" : Number(element.value)) : element.value;
    root.addEventListener("change", (event) => {
        const target = event.target;
        if (target?.matches?.("[data-upscale-enabled]")) {
            store.set(setGlobalUpscaleEnabled(store.get(), target.checked));
            return;
        }
        const input = target?.closest?.("[data-path]") || target;
        const path = input?.dataset?.path;
        if (!path) return;
        const [section, key] = path.split(".");
        store.patch(section, key, readInput(input));
    });
    let capabilities = null;
    const setConditional = (name, hidden) => {
        root.querySelectorAll(`[data-conditional="${name}"]`).forEach((element) => { element.hidden = hidden; });
    };
    const updateLocale = (language = locale()) => {
        const lang = language === "en" ? "en" : "zh";
        root.querySelectorAll("[data-post-text]").forEach((element) => {
            element.textContent = POST_TEXT[lang][element.dataset.postText] || element.textContent;
        });
        root.querySelectorAll("[data-field-label]").forEach((element) => {
            const pair = element.dataset.fieldLabel === "resolved_target" ? ["Final Size", "最终尺寸"] : POST_LABELS[element.dataset.fieldLabel];
            if (pair) element.textContent = pair[lang === "zh" ? 1 : 0];
        });
        root.querySelectorAll("select[data-path]").forEach((select) => {
            const labels = POST_OPTION_LABELS[select.dataset.path];
            if (!labels) return;
            for (const option of select.options) {
                const pair = labels[option.value];
                if (pair) option.textContent = pair[lang === "zh" ? 1 : 0];
            }
        });
        const vsr = root.querySelector('[data-capability="nvidia_rtx_vsr"]');
        if (vsr && capabilities) {
            const ready = !!capabilities.dependencies?.nvidia_rtx_vsr;
            vsr.textContent = `RTX VSR: ${POST_TEXT[lang][ready ? "runtime_detected" : "missing_no_downgrade"]}`;
        }
        // Pass the resolved language through: render() would otherwise consult
        // locale() and re-render English summaries over translated labels.
        render(store.get(), lang);
    };
    const render = (config, forcedLang = null) => {
        root.querySelectorAll("[data-path]").forEach((input) => {
            const [section, key] = input.dataset.path.split(".");
            const value = config[section]?.[key];
            if (input.type === "checkbox") input.checked = !!value;
            else if (String(input.value) !== String(value ?? "")) input.value = value ?? "";
        });
        const visible = globalRefineVisibility(config);
        root.querySelector("[data-second-sampling-body]").hidden = !visible.secondSampling;
        root.querySelector("[data-upscale-enabled]").checked = visible.upscaleEnabled;
        root.querySelector("[data-upscale-body]").hidden = !visible.upscaleEnabled;
        setConditional("seed_offset", !visible.seedOffset);
        setConditional("tiled", !visible.tiled);
        setConditional("temporal", !visible.temporal);
        setConditional("upscale_model", !visible.upscaleModel);
        setConditional("learned_latent", !visible.learnedLatent);
        setConditional("vsr_quality", !visible.vsr);
        setConditional("vsr_status", !visible.vsr);
        setConditional("seedvr2", !visible.seedvr2);
        setConditional("aspect", !visible.aspectMegapixels);
        setConditional("megapixels", !visible.aspectMegapixels);
        setConditional("width", !visible.customSize);
        setConditional("height", !visible.customSize);
        const fv=faceRefineVisibility(config);
        setConditional("face_detector_model",!fv.detectorModel);
        setConditional("face_canvas_size",!fv.manualCanvas);
        setConditional("face_sam_model",!fv.sam);
        setConditional("face_sam_advanced",!fv.sam);
        setConditional("face_identity",!fv.identity);
        setConditional("face_fallback",!fv.fallback);
        const av=audioRefineVisibility(config);
        setConditional("audio_custom",!av.customRoom);
        const [w, h] = directorSize();
        const lang = forcedLang || locale();
        root.querySelector('[data-summary="global_refine"]').textContent = globalRefineSummary(config, w, h, lang);
        root.querySelector('[data-summary="face_refine"]').textContent = faceRefineSummary(config, lang);
        root.querySelector('[data-summary="audio_refine"]').textContent = audioRefineSummary(config, lang);
        const [tw, th] = resolveGlobalTarget(config, w, h);
        root.querySelector("[data-resolved-target]").textContent = `${tw}×${th}`;
        root.querySelector('[data-section="global_refine"]').classList.toggle("mmx-post-disabled", !config.global_refine.enabled);
        root.querySelector('[data-section="face_refine"]').classList.toggle("mmx-post-disabled", !config.face_refine.enabled);
        root.querySelector('[data-section="audio_refine"]').classList.toggle("mmx-post-disabled", !config.audio_refine.enabled);
    };
    const unsubscribe = store.subscribe(render);
    render(store.get());
    updateLocale(locale());

    if (fetchApi) fetchApi("/minimax/motion-director/postprocess_capabilities").then((response) => response.json()).then((caps) => {
        const fill = (path, rows) => {
            const select = root.querySelector(`[data-path="${path}"]`);
            const current = select.value;
            select.innerHTML = '<option value="">—</option>' + (rows || []).map((name) => `<option value="${name}">${name}</option>`).join("");
            select.value = current;
        };
        fill("global_refine.upscale_model", caps.upscale_models);
        fill("global_refine.latent_upscale_model", caps.latent_upscale_models);
        fill("face_refine.detector_model", caps.face_detectors);
        fill("face_refine.fallback_detector", ["none", ...(caps.face_detectors || [])]);
        fill("face_refine.sam_model", caps.sam_models);
        const h3LatentModels = caps.latent_upscale_models || [];
        const currentGlobal = store.get().global_refine;
        if (!currentGlobal.latent_upscale_model && h3LatentModels.length === 1) {
            store.patch("global_refine", "latent_upscale_model", h3LatentModels[0]);
        }
        const detectors=caps.face_detectors||[];
        const currentFace=store.get().face_refine;
        if(!currentFace.detector_model&&detectors.length){
            const preferred=detectors.find((name)=>/face.*yolo/i.test(String(name)))||detectors[0];
            store.patch("face_refine","detector_model",preferred);
        }
        capabilities = caps;
        const ds=root.querySelector('[data-capability="face_detector"]');
        if(ds){ds.textContent=detectors.length?"":POST_TEXT[locale()==="en"?"en":"zh"].no_face_detector;ds.classList.toggle("bad",!detectors.length);}
        const vsr = root.querySelector('[data-capability="nvidia_rtx_vsr"]');
        const ready = !!caps.dependencies?.nvidia_rtx_vsr;
        vsr.classList.toggle("bad", !ready);
        updateLocale(locale());
    }).catch(() => {});
    return { root, render, updateLocale, destroy: unsubscribe };
}

export { DEFAULT_CONFIG, ROOM_NAMES };
