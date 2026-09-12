import assert from "node:assert/strict";
import fs from "node:fs";
import {DEFAULT_CONFIG,ROOM_NAMES,audioRefineSummary,audioRefineVisibility,faceRefineVisibility,globalRefineSummary,globalRefineVisibility,normalizePostprocessConfig,setGlobalUpscaleEnabled} from "../minimax_postprocess_ui.mjs";

let cfg=normalizePostprocessConfig({global_refine:{enabled:true,mode:"refine",seed_mode:"inherit",resolution_mode:"follow_director",upscale_method:"lanczos"}});
assert.equal(cfg.version,11);
assert.deepEqual(globalRefineVisibility(cfg),{secondSampling:true,upscaleEnabled:false,seedOffset:false,upscaleModel:false,learnedLatent:false,vsr:false,aspectMegapixels:false,customSize:false});
assert.match(globalRefineSummary(cfg,1376,768,"zh"),/保持原 Seed/);
cfg=setGlobalUpscaleEnabled(cfg,true); cfg.global_refine.upscale_method="nvidia_rtx_vsr"; cfg.global_refine.vsr_quality="high"; cfg.global_refine.resolution_mode="aspect_megapixels";
assert.equal("vsr_source" in cfg.global_refine,false);
assert.match(globalRefineSummary(cfg,1376,768,"zh"),/RTX VSR High/);

const latent=normalizePostprocessConfig({global_refine:{enabled:true,mode:"upscale",upscale_method:"h3_learned_latent",latent_upscale_model:"h3.safetensors",latent_upscale_variant:"3D",latent_upscale_precision:"BF16",latent_upscale_device:"CPU"}});
assert.equal(latent.global_refine.upscale_method,"h3_learned_latent");
assert.equal(latent.global_refine.latent_upscale_model,"h3.safetensors");
assert.equal("latent_upscale_variant" in latent.global_refine,false);
assert.equal(latent.global_refine.latent_upscale_precision,"bf16");
assert.equal(latent.global_refine.latent_upscale_device,"cpu");
assert.equal(globalRefineVisibility(latent).learnedLatent,true);
assert.match(globalRefineSummary(latent,1376,768,"zh"),/H3 Learned Latent →/);
assert.doesNotMatch(globalRefineSummary(latent,1376,768,"zh"),/\b2D\b|\b3D\b/);

const uiSource=fs.readFileSync(new URL("../minimax_postprocess_ui.mjs",import.meta.url),"utf8");
assert.doesNotMatch(uiSource,/Requires the separately installed LBH|需要另外安装 LBH/);
assert.match(uiSource,/No separate LBH custom node is required/);
assert.match(uiSource,/无需另装 LBH 自定义节点/);
assert.match(uiSource,/architecture is detected from the weights/);
assert.match(uiSource,/架构会直接从权重自动识别/);
assert.doesNotMatch(uiSource,/field\("Latent Variant",\s*"global_refine\.latent_upscale_variant"/);
assert.doesNotMatch(uiSource,/2D \+ Temporal \(recommended\)|2D \+ Temporal（推荐）/);
assert.match(uiSource,/field\("Face Detector Model",\s*"face_refine\.detector_model"/);

const face=normalizePostprocessConfig({face_refine:{enabled:true,detector:"ultralytics",canvas_mode:"manual",mask_mode:"sam",identity_track:true,fallback_detector:"person_yolov8m-seg.pt"}});
assert.deepEqual(faceRefineVisibility(face),{detectorModel:true,manualCanvas:true,sam:true,identity:true,fallback:true});
assert.equal(face.face_refine.smooth_window,21); assert.equal(face.face_refine.size_smooth_window,51);
assert.equal(face.face_refine.base_denoise,0.45); assert.equal(face.face_refine.feather,24);
const migrated=normalizePostprocessConfig({version:3,face_refine:{smooth_window:9,size_smooth_window:13,base_denoise:0.22,feather:0.12}});
assert.equal(migrated.face_refine.smooth_window,21); assert.equal(migrated.face_refine.size_smooth_window,51);
assert.equal(migrated.face_refine.base_denoise,0.45); assert.equal(migrated.face_refine.feather,24);

// ---- Audio Room -------------------------------------------------------------
assert.match(uiSource,/data-section="audio_refine"/,"the panel must render an Audio Room column");
assert.match(uiSource,/field\("Room",\s*"audio_refine\.room"/,"the room preset selector must exist");
assert.match(uiSource,/audio_refine\.per_segment/,"the per-segment opt-in must exist");

const audio=normalizePostprocessConfig({audio_refine:{enabled:true,room:"Bathroom",reverberance:500,hf_damping:-80,gain_db:999,pre_delay_ms:-5}});
assert.equal(audio.audio_refine.enabled,true);
assert.equal(audio.audio_refine.room,"bathroom","room names must normalise to lowercase keys");
assert.equal(audio.audio_refine.reverberance,100);
assert.equal(audio.audio_refine.hf_damping,0);
assert.equal(audio.audio_refine.gain_db,20);
assert.equal(audio.audio_refine.pre_delay_ms,0);

// An unknown room must clear to "" so the six explicit values take over.
assert.equal(normalizePostprocessConfig({audio_refine:{enabled:true,room:"swimming_pool"}}).audio_refine.room,"");
// An empty string must fall back to the default, NOT clamp to the low bound.
assert.equal(normalizePostprocessConfig({audio_refine:{enabled:true,reverberance:""}}).audio_refine.reverberance,40);
assert.equal(normalizePostprocessConfig({audio_refine:{enabled:true,gain_db:null}}).audio_refine.gain_db,0);

// A named room supplies all six values, so the manual fields hide.
assert.deepEqual(audioRefineVisibility(audio),{customRoom:false,limiter:true,perSegment:false});
assert.equal(audioRefineVisibility(normalizePostprocessConfig({audio_refine:{enabled:true,room:""}})).customRoom,true);
assert.equal(audioRefineVisibility(normalizePostprocessConfig({audio_refine:{enabled:true,room:"",reverb_enabled:false}})).customRoom,false);
assert.equal(audioRefineVisibility(normalizePostprocessConfig({audio_refine:{enabled:true,room:"hall",per_segment:true}})).perSegment,true);
assert.equal(audioRefineVisibility(normalizePostprocessConfig({audio_refine:{enabled:true,room:"",gain_db:-4}})).limiter,false);

assert.match(audioRefineSummary(audio,"en"),/Bathroom/);
assert.match(audioRefineSummary(audio,"zh"),/浴室/);
assert.match(audioRefineSummary(normalizePostprocessConfig({}),"en"),/Disabled/);
assert.match(audioRefineSummary(normalizePostprocessConfig({audio_refine:{enabled:true,room:"",reverberance:33,room_scale:44}}),"en"),/Rev 33% · Size 44%/);
assert.match(audioRefineSummary(normalizePostprocessConfig({audio_refine:{enabled:true,room:"bar",per_segment:true}}),"en"),/Per-segment/);

// Parity with the Python side: these two lists are hand-maintained in two
// languages and the summary/dropdown silently break when they drift.
const pyEffects=fs.readFileSync(new URL("../../../director/audio_effects.py",import.meta.url),"utf8");
const pyRooms=[...pyEffects.matchAll(/^\s{4}"([a-z_]+)":\s+RoomSpec\(/gm)].map((match)=>match[1]);
assert.ok(pyRooms.length>=9,"could not read ROOM_PRESETS from audio_effects.py");
assert.deepEqual([...ROOM_NAMES].sort(),[...pyRooms].sort(),"JS ROOM_NAMES drifted from Python ROOM_PRESETS");

const pyConfig=fs.readFileSync(new URL("../../../director/audio_refine_config.py",import.meta.url),"utf8");
for(const key of ["reverberance","hf_damping","room_scale","stereo_depth","pre_delay_ms","wet_gain_db","gain_db"]){
    const match=pyConfig.match(new RegExp(`"${key}":\\s*(-?[\\d.]+)`));
    assert.ok(match,`Python DEFAULT_AUDIO_REFINE is missing ${key}`);
    assert.equal(DEFAULT_CONFIG.audio_refine[key],Number(match[1]),`JS default for ${key} drifted from Python`);
}
console.log("postprocess UI state tests passed");
