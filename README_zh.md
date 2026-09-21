# MiniMax H3 Motion Director  [English](README.md) | [简体中文](README_zh.md)

![Version](https://img.shields.io/badge/version-v1.13.0-2ea44f)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)
![ComfyUI](https://img.shields.io/badge/ComfyUI-custom%20node-6f42c1)

> **维护分支（fork）**：本仓库在原版 j955229 基础上新增：
>
> - **v1.13.0 新增**：**边界锚点（Boundary Anchors）**——在正式渲染分段之前，先为每个分段边界渲染一小段「锚点」（默认 22 帧 ≈ 0.92 秒，按 `17k+5` 网格取整，因此每个边界可以有自己的帧数），用该分段自己的参考素材、共享提示词与该边界的**节拍（beat）**生成，并把确定下来的画面缓存为 `A<ii>_s<seed>_v1_f22.png` + JSON 侧车文件（与分段缓存同目录）——锚点渲染一次、审阅一次，之后每次运行与 Resume 都复用它。正式分段随后会拿到「开边界」与「闭边界」的锚点作为额外的 `<Picture N>` 参考（`mode: soft`），并带上对应的提示词行。**不再靠断言，而是有实测量**——链式渲染让第 N+1 段依赖第 N 段的成片，误差会累积：6×7.3 秒 A/B（`docs/ANCHOR_LADDER_PROPOSAL.md`）显示，帧直方图相关性相对第 1 段在前三段维持约 0.80，随后掉到第 5 段 **0.53**、第 6 段 **0.41**，背景/光照漂移升至 Δ72，而且链条**跑偏了剧本**（第 2 段自行加了一个提示词里没有的「扑向镜头」动作）；改由边界锚点约束后，六段稳定性平在 **0.72–0.81**、世界漂移最低（Δ23.9–43.4）。整轮锚点遍历的成本约为正式渲染的 10%（4 个锚点 × 0.9 分钟，对比约 32 分钟的分段）。**每个边界都在负载里可控**：`timeline_data["anchors"]` 携带 `mode`、`chunkFrames`、`seedBase` / `seeds[]`、`beats[]`、`promptTemplate`（`{{shared}}`、`{{beat}}`、`{{index}}`）、`injectPrompt`、`renderPass`、`preRollOnly`、`forceRender`、`onlyIndices`、`boundaries`、`draft`，分段还可以用 `anchorPrompt` 声明自己的**收尾姿态**（或用 `anchorIn` / `anchorOut` 直接指向某个边界）。选区是**严格**的：`all` / `bookends` / `none` / 显式下标表决定「哪些边界存在」，未选中的边界既不渲染也不参与约束——「只做首尾」真的只花两次渲染。**预演（Pre-roll）＝整片的故事板，在花掉任何一次正式分段之前**：只渲染选中的锚点、跳过正式分段，并把它们组装成故事板 MP4（走本插件原有的 `CreateVideo`/`SaveVideo` 输出）与带标注的接触印相图，于是可以在每拍还只有 0.9 秒时就先判断节拍对不对；**草稿（Draft）**则是另一头：按比例缩减画幅与步数渲染正式分段（`scale`、`steps`），并写入独立的缓存命名空间（`cache_variant`），预览永远不会污染正式缓存。**锚点条带**（`web/js/minimax_anchor_strip.mjs`）位于时间线下方、可折叠为一条细栏：每个边界一张卡片（缩略图、序号、种子、状态、节拍文本），卡片上可选中/取消、**只渲染该锚点**、批准、换种子重掷；细栏上有预设 **All** / **Bookends** / **Rendered**、**Pre-roll**、**Draft**、全部批准 / 清空。点击缩略图会把播放头移动到该边界，ctrl+点击打开 PNG，折叠状态与卡片数据随工作流保存。新增路由模块 `director/anchor_routes.py`（计划、状态、单点渲染、批准、删除），并新增 `docs/ANCHOR_LADDER_PROPOSAL.md` 记录实验、数值与阶段计划（硬首尾帧模式尚未发布）。修复：**锚点失败不再无声消失**（合成分段用下标偏移 `1000 + n` 去查「上一段」，抛出的 `IndexError` 被吞进无人打印的告警列表——整遍渲染报告成功、磁盘上却没有任何文件，现在每个锚点失败都会连同边界与原因写进日志）；**单卡片渲染按钮不会再卡在「渲染中」**（它复用了已存在的 PNG，缩略图不变于是状态永远不结束；现在强制重渲染、改看运行历史，并在超时时明确报出；重掷会留下多个种子的文件，因此条带优先使用与当前种子匹配的那张，删除按钮会清掉全部）；**预览不会再吞掉下一次正式运行**（条带的临时标记就写在节点渲染所用的同一份 `timeline_data` 里，而它们只在条带等待自己那次运行结束后才还原——这段时间内按下的 **Start run** 会继承「只预演」，于是锚点渲染完就结束、约 1.2 秒报告成功却没有任何正式分段；现在排队后立即还原，条带载入时也会清除残留标记）；`first-pass sampling` 日志行此前打印节点基础种子而非该分段真正使用的种子（看起来像逐边界种子没生效）；以及 `web/js/tests/minimax_motion_settings.test.mjs` 用「文件长度一半」来切分两本字典，新增条带字符串后中点落进了英文块（现改为按 `const EN = {` 边界切分）。
> - **Re-ground 分段（防累积漂移）**：时间线每段边界下方新增 **R 圆圈**，左键切换（开启后变琥珀色）。开启的段落会从「链首 root」而非上一段重新锚定上下文，用于长片每 3–5 段设置一次，配合 Latent Scale Lock 与 Color Re-anchor 抑制色彩/画面漂移。
> - **性能修复**：修复打开 Director 面板时因超长提示词逐字裁剪导致的长时间卡顿（改为二分查找 `fitCanvasText`，实测约快 525 倍）；批量卡片启用 `content-visibility` 优化滚动。
> - **新版 ComfyUI 兼容**：H3 节点改为关键字传参，兼容 v0.34.x 之后 io.Schema / ComfyNode 重写版 ComfyUI，修复 `//: 'str' and 'int'` 崩溃。
> - **v1.12.0 新增**：**界面不再越用越卡**——长时间使用后任何操作都要等十秒，根因是每个节点的音频角色面板在 `onDrawBackground`（LiteGraph **每帧**都会调用的钩子）里重建整块 DOM，而每次重建又通过「时长探测已就绪」的回调把自己重新排队，形成活锁：实测空闲标签页每秒产生 **4,613 次 DOM 变更批、13,950 次变更**，单个浏览器进程持续占满一个核心（96%），整个 ComfyUI 界面都排在这条主线程之后——所以 CPU 与显存看起来都很空，操作却要等十秒（服务端发往页面的套接字也因此积压数 MB）。现在重建按渲染签名判定（状态没变就完全不碰 DOM）、绘制钩子每 250 ms 才做一次兜底同步、时长只有在**真正新发现**时才算变化、`schedule()` 会先清掉上一轮定时器；同一标签页、同一工作流实测降到 **每秒 4 批、99 次变更**。**不再为每次 DOM 变更全文档扫描**——两个扩展此前监视 `document.body`，对应用产生的每一批变更都执行一次「四个全文档查询 + 每张报告卡片强制重排」的完整扫描；现在只对自己相关的 DOM 过滤变更、每帧最多合并一次扫描（下限 400 ms）并保留 2 秒兜底、报告卡片属性改为按卡片监听、标签页隐藏时不做任何工作，250 ms 的输入/分区轮询在标签页隐藏或节点已移除时也会直接跳过。**校验阶段就能看到每段是否放得下**（按序列长度与当前可用显存逐段估算，给出 `ok` / `tight` / `over` 与具体改法，仅告警、不阻断渲染），**OOM 后运行面板直接给出可点击的重试**（`Retry S4 at 243 frames` / `Set reference size to 1024 px and retry`），**红色「素材缺失」芯片可点击重新挂接**；新增 **`scripts/drift_report.py`**——从已渲染的分段文件测量链的接缝、色彩、细节与噪声趋势（纯 CPU、渲染中也能安全运行），接缝与「段内相邻帧的真实变化」对比判定：`1.0x` 表示接缝与普通运动不可区分，`5x` 以上为明显跳切。
> - **v1.11.0 新增**：**整包级设置面板**——顶栏齿轮打开一份「每个 ComfyUI 用户一份」的应用级配置（所有节点、所有工作流共用，而不是某个项目的控件组）：**机器**（显卡、总/剩余显存、算力、pack / ComfyUI / Python / torch 版本，以及本机真正能导入的注意力后端：`sdpa`、`sage`、`comfy_kitchen` int8、`xformers`、`flash_attn`、`triton`；显存被别的程序占住时档位自动降一级并说明原因，也支持手动指定设备/显存）；**后端一致性检查**（把当前节点图与机器对照，在渲染之前按节点 id 点名「本机跑不了的后端」，而不是等采样中途报 CUDA 错误）；**新内容基线**（画幅比例 + 像素量或固定宽高、默认分段帧数、每段最大帧数、参考图长边、连续性与段间清理显存默认值；只影响**新建**的分段/卡片/长片镜头，改动现有项目必须显式按「应用到本项目」，因为重写分段会让分段缓存与 Resume 的完成标记失效）；**运行与界面**（每段自动保存工作流、常驻模型、详细日志、默认导出模式、语言、实时预览、预览音频、缓存告警体积；工具栏语言按钮与这里的语言是同一个值）；**缓存管理**（列出本插件写入的全部缓存，按项目节点与类型给出真实体积并排序，显示运行状态与完成数；支持按项目或按类型清理，二次确认，正在渲染时拒绝执行）；**诊断**（一键复制/下载版本、机器、后端探测、设置、缓存合计、运行状态、当前项目形状、后端告警与上次运行报告，把报错截图换成一段文本）。新增模块：`web/js/minimax_motion_settings.mjs`（纯规则，带单测）、`web/js/minimax_settings_ui.mjs`（面板）、`lib/machine_profile.py`（探测与档位基线）、`director/motion_settings.py`（存储与校验）、`director/settings_routes.py`（路由）；所有基线都已预对齐 H3 的 32 像素画幅倍数与 17k+5 帧网格，且基线不会产出无法渲染的分段（任务自身下限与 `MAX_GEN_FRAMES` 仍然优先）。**默认分段长度现在与硬件真实承载相符**——1376x768、满尺寸参考、345 帧的序列在已经占用 22 GB 的显卡上仍要申请一整块约 3 GB 的显存，最终在稀疏注意力阶段以仅剩 63 MiB 失败，原先的档位基线过于乐观；现在 24–32 GB 显卡默认 1 MP 下 7 秒分段（`ref_max_size` 1024）、上限 10 秒，工作站档为 10 秒 / 15 秒，指南也新增「实际上限」一节并给出实测依据：注意力开销约随序列长度平方增长，175 帧为 1×，243 帧约 1.9×，345 帧约 3.8×。**增强器的按钮从「设置」改名「扩写设置」/「Enhancer…」**，避免与整包设置齿轮混淆。**导出视频是否携带工作流由你决定**——ComfyUI 的 `Save Video` 会把 `workflow` 与 `prompt` 标签写进容器（这也是成品 mp4 能拖回画布复原节点图的原因，对本插件而言即整个项目：时间线、逐段提示词、参考素材、采样参数），同时这些标签也会把提示词、模型/LoRA 名称与本地路径带进每一个副本；因此设置面板新增**导出**页（`跟随 ComfyUI` 默认 / `总是嵌入` / `从不嵌入`，并写明当前生效状态与 `--disable-metadata` 标志），结果页保存卡片也有同样的三选一，该页还可以**清除已保存文件里的元数据**（ffmpeg 直接重封装、码流原样拷贝、输出加 `_clean` 后缀、路径限制在 ComfyUI 输出目录内）；新模块 `director/video_metadata.py`，每条命令都带 `-nostdin` 并把 stdin 指向 DEVNULL——继承终端的 ffmpeg 会被 SIGTTIN 停住并忽略超时的 SIGTERM，从而把一次无人值守的清除变成永久挂起。**修复：材质库添加的参考素材现在会与提示词中的提及重新挂钩**——三处叠加故障：**类型词表不一致**（材质库用媒体类型 `image`，提示词/槽位/引用块用 `picture`，于是「未挂接提及」的匹配永远不成立、每次都落到新 id，红色芯片怎么加都不会变绿；现已在 `minimax_reference_assets.mjs` 中统一归一化，同一文件无论从材质库添加还是从槽位上传都会得到同一个 id）、**不重绘**（应用后只刷新参考面板、没有重绘提及芯片，即使 id 正确，旧的红芯片也会一直留在屏幕上直到再次输入提示词）、**名字不可读**（素材被复制为 `input/minimax_material_library/mat_<id>.<ext>`，参考素材显示的就是这个文件名；现在显示素材标题，载荷清洗会保留它，保存/重载后仍在）；**红色「素材缺失」芯片会说明它找不到什么**——悬浮提示给出它想要的 id 与本提示词作用域内实际拥有的图片/视频/音频素材，控制台对每个未知 id 只警告一次。**修复：优雅 Stop 不再以 Face Refine 报错收场**——启用 Face Refine 时，分段收尾校验要求每个被选中的分段都有终态，于是第 1 段后按 Stop（或复用缓存前缀的 Resume）会在 Assembly 之后抛错并把 Stop 本该保留的半成品导出丢掉；现在差值会被归因（Stop / Resume 记日志并保留已完成前缀，无法解释的缺段仍会抛错）。
> - **v1.10.0 新增**：**角色替换链可以离开原片**——替换任务的每一行过去都是源视频上的一个掩码窗口，因此链条永远走不出素材覆盖的范围；现在某一行可以是**生成行**（`"kind": "generate"`）：没有源区间，完全按自己的提示词与参考渲染，可位于链中或素材结束之后；行仍按表格顺序渲染与导出，连续性仍由上一段的 Motion Context 提供，生成行还可选择与前一行的接续方式——`r2v` 以它为上下文并把其最后一帧作为 `<Picture>` 锚点，`i2v` 则把该帧锁为该行的首帧；时间线归一化不再把生成行裁到源素材总帧数（那恰好会删掉「素材结束之后」的那一行），面板用 **G** 与窗口的 **W** 区分、不在生成行上显示仅窗口可用的掩码控件、覆盖徽章只统计窗口并单列 `n generated`，**长片替换**会保留生成行并放回原位；不带 kind 的行行为完全不变。**故事 → 分段，且出现在它本该出现的位置**——用几句话描述整个故事、设定分段数与每段时长，一次模型调用即可拆成一段「世界」描述加每段一拍，并遵循本插件既有的规则（每段一次连续镜头、每一拍都要有变化、每段收在下一段能接上的姿态、她的外貌只描述一次）；该区块位于增强面板内，而 `t2v` / `i2v` / `r2v`（提示词组卡片）与长片模式恰恰不显示「设置」按钮所在的那一行，因此批量面板与长片面板现在自带 **故事 → 分段** 按钮，并且提示词组被当作它本来的样子——一串生成分段——缺少的卡片会按该时长**自动创建**（`durationSec`，由归一化器按 H3 的 24 fps 生成 17k+5 帧）；长片模式只写入已有镜头，手工排布的普通视频／角色替换时间线仍不会被重新计时。**统一到模型自己的 24 fps**——H3 没有 fps 输入：帧数即时长，联合视频+音频潜变量固定在 24 fps；30 fps 项目因此同时存在两种帧率，而所有真正指「画面秒数」的地方都误用了项目帧率：分段音频按 `帧数 ÷ 30` 裁剪（5.71 秒画面前留下静音尾巴）、合并导出的 `Export all` 被节点的 `fps` 输出打上 30 fps（20.29 秒的影片回放成 16.23 秒，而它旁边的分段片段是按 24 fps 写出的）、Audio Drive 区块按短了 20% 的画面时长校验并写进提示词、接缝诊断也用错帧率描述合并音轨；现在 `lib/h3_rate.py` 统一持有该常量与规则——源素材换算用项目帧率（窗口起止**本就是**源帧），任何由渲染帧推导的秒数用模型帧率——整条链因此自洽，**Validate** 会以 `frame_rate_not_24` 提示并说明会发生什么；诚实的余项是速度：交给 24 fps 模型的 30 fps 帧仍会慢 25%，因此建议替换角色所用的素材直接使用 24 fps 源。**增强器终于知道自己在哪、在看什么**——视觉帧改为取自该分段自己的窗口（此前是从整段文件里均匀取三个瞬间，长片里每个窗口都取到同样三帧），且从四帧起按**动作对**采样（相隔几帧的近重复帧），因为一组静帧无法表达运动；动作 caption 改为**先写动作**（一次实跑因为把房间写在前面而在半路截断）；「其实只是模型自言自语」的 caption 不再被塞进提示词；**你自己的提示词配方**可以放在包更新无法覆盖的文件里（`recipes.json`，`recipe_templates/` 为每种形式附带模板），面板 `浏览…` 可载入，下拉框仍保留本插件自带的形式；替换窗口保留你自己写的运动描述（caption 看不到不留帧差的运动），并且 `<Picture N>` 形式的替换块现在也带上 RefMod 形式一直有的「保持源姿态」那句——一次实跑因此把手伸到了背后而不是保持在身下。另修复：失效缓存的 `.mjs` 会让增强面板静默失效直到手动清缓存（现有三层防护），以及子目录中的参考图被静默丢弃。
> - **v1.9.0 新增**：**公共参考素材（Common References）改为「素材池」而非「回退」**——此前某段渲染时只用「本段自己的图」**或**「公共块」，二者互斥：本段只要自带一张参考图，共享的角色设定图就会被静默丢弃，而提示词里的 `<Picture N>` 是按素材池编号写下的，于是它指向的图根本没有被送到渲染；现在两个 plan builder 走同一套编译（本段保留的公共素材在前、本段自有素材在后，从 `<Picture 1>` 起密集重编号），`useCommonAssets` / `excludedCommonAssetIds` 生效，官方上限（9 图 / 3 视频 / 3 音频）超限时给出点名要删什么的报错；视频时间线上的 `@` 提及也按本段解析，且「文件已消失的提及」原样保留而不再让整次渲染失败。**增强器的视觉通道与渲染看到同一份参考**——角色替换的身份在公共块里，只按「本段」收集视觉会一张参考图都收不到，caption 因此描述了一个它从未见过的角色；现在按同一顺序解析同一份列表，并把「每张图对应哪个槽位」告诉模型。**RefMod 可按窗口选择**——采集到的一组 mod 会被附加到每个分段，只属于部分窗口的 mod 无从表达；现在每个窗口都有 `refmod` 开关（替换窗口列表，或分段右键菜单），随 plan 传递并在两处 conditioning 点（含 5 帧 Source Bridge）生效。**带参考图的 RefMod 窗口可以同时使用图片**——此前压制身份描述是因为 mod 只到达 DiT、关于面容的文字会与参考对抗；当窗口同时带有编号参考图时，图片对文本编码器同样可见，于是它们会被 caption 描述，提示词块也把 mod 与图片写成「同一个人」；没有图片时仍保持原有压制。同版还包含：`rv2v` 可打开公共参考（按钮 + 素材库目标）、替换窗口列表点击即选中该窗口、`卸载模型` 会报告「原本占用什么 + 现在显存多少」、增强按钮运行中保持界面语言、以及 **仅润色措辞（Polish wording only）** 只改行文不改标签／标题／`[Shot N]`。
> - **v1.8.4 新增**：**提示词增强器完全在 ComfyUI 内运行**——直接用 llama.cpp 加载你自己 `models/LLM` 目录下的 GGUF 模型，不再需要 Ollama / API Key / 第二个服务；模型列表来自磁盘上真实存在的文件，推荐的 Qwen3.8 27B abliterated 一键下载（先标体积再拉取），下载进度按 huggingface_hub 自身暂存目录实测，面板重载后仍继续；显存吃紧时沿「显存阶梯」逐级降级（减少 GPU 层数 → 缩小上下文）而不是报错，`卸载模型` 可把显存直接还给渲染（Python 路由现已支持 Local 后端，此前点击只会得到 `Current API format does not support model unload`）。**新增「从图像构建提示词」（caption 模式）**——移植自外部的 Character Remake（「Masked Motion + QwenVL」）工作流：不让语言模型「写结构」，而是用两次窄范围视觉提问（「这个角色长什么样」「这个源窗口发生了什么」）分别看图，再由本插件自己的代码把答案拼进分段模板，因此所有标题、角色行、保留规则与丢弃句都由代码掌控，不会被重排、遗漏或凭空发明；身份只看参考图，动作只看源帧。覆盖六种配方（带/不带 RefMod 的角色替换、ref2va、源编辑、首帧、首尾帧），并首次把 i2v/fl2v 的首尾帧交给模型看图（此前面板根本不发送这些帧）。**RefMod 角色终于可被描述**——mod 在文本编码之后以匿名潜变量形式附加，提示词无法描述它，指南要求的 `wardrobe:` 行长期为空；现在用 H3 视频 VAE 解码 mod 自身潜变量并加注，输出一行服装与最多一个 2–4 词线索（不描述面容：关于身份的文字只会与参考图对抗）。**可隐藏被替换的原演员**——把动作帧的主体区域反相后再交给 caption（rembg 显著性掩码，CPU，每帧约两秒），避免模型偶尔描述原演员而与替换参考图打架；该选项默认关闭，且当掩码无法生成时会在说明中点明。另新增 `H3 提示词规则（精简）`、`配方（Recipe）`下拉（明确目标结构，`Auto` 保持原有行为）、以及面板上的推理后端提示（CUDA / Vulkan / Metal / CPU，并在「有 GPU 构建但后端从未加载」时警告一次，即编译目标 CUDA 大版本不匹配而静默回退 CPU）。修复：**`增强` 每次都返回 500**（`is_replace_task_prompt` 未导入；规则测试直调 `enhance_prompt_sync`、面板 harness 打桩 HTTP、QA 只走 GET，因此套件全程绿灯，现已补 `tests/test_enhance_route_handler.py` 直调真实 handler，并因此发现第二个 bug——紧凑规则开关从未传给增强器）；**视觉模式在 Qwen3-VL 上必然失败**（llama.cpp 只为文本格式化器注册 Transformers 的 Jinja 助手，多模态 handler 用的是裸沙箱环境，而 Qwen3-VL 模板在守卫分支调用 `raise_exception` → `UndefinedError`；首次修复因模块路径写错而静默无效，故测试直接断言补丁打到了它声称的类上）；**caption 模式无法「不发送」system 轮**（`MTMDChatHandler` 会在 system 为空时补一条默认 system，导致两条 system 消息 → `TemplateError: System message must be at the beginning.`）；**增强完成后输入框里的提示词没变**（两个提示词框都由 mention 控制器接管并维护自己的富文本状态，直接写 `.value` 会被控制器下一次读取覆盖回去——每一步都报成功，结果却静默回滚；现改为经 `setValue` 写入）。
> - **v1.8.3 新增**：**可选「常驻放大模型」（`latent_upscale_cache_model`，默认关闭）**——放大阶段在 H3 DiT 卸载之后执行，因此每次调用都是一次完整的「加载 → 释放」循环，叠加在 DiT 自身的卸载/重载之上；勾选后放大模型常驻显存，多段渲染不再逐段重载，代价是本次会话余下时间一直占用显存、并与重新载入的 DiT 共享显卡，故默认关闭，面板在复选框旁写明取舍（中英）。缓存按 `(权重路径, dtype, 设备)` 单条键控，精度或设备变更会重建；旧模型**先释放再构建**，两者不会同时在显存中；取消勾选即释放。**修复学习式潜空间放大每次调用重读并重转权重**：此前每次都从磁盘重新读取并重跑 float8 → fp16 转换，现按「路径 + 大小 + mtime」在内存中缓存最近两份 state dict（换文件即失效），`build_model` 只读取形状、`load_state_dict` 会复制，因此可直接共享无需拷贝。**修复放大阶段显存实际未归还**：清理时先删除模型，随后在 `mean`/`std` 仍为活动显存张量的情况下调用 `empty_cache()`，而不可达但未回收的张量依然占着显存——与段间显存清理踩过的是同一个坑，现已先解除全部设备引用并回收再清空。**修复 v1.8.2 的界面改动根本没到浏览器**：ComfyUI 按 URL 缓存前端模块，只有 `?boot=` 令牌变化才会重新下发；v1.8.2 有两个模块内容变了但令牌没动（「覆盖整段视频」、**cont** 复选框、常驻放大开关、外部补丁说明），浏览器一直跑缓存副本，文件在磁盘上、ComfyUI 也一直在提供新版本，只是没有任何请求去取它；现已同步提升两个令牌。
> - **v1.8.2 新增**：**角色替换窗口接力（continuity anchor）**——替换窗口彼此独立重渲染，交界处两个窗口各自「猜」同一源帧，角色姿态因此会跳变；现在窗口可把**上一个窗口的最后一帧**作为额外 `<Picture>` 参考注入（并附一行提示词指名该图），使角色从上一段结束的姿态接续，默认开启、首段自动跳过、可按窗口用 **cont** 复选框关闭（适用于刻意留空隙的窗口），缓存复用的窗口同样记录尾帧，断点续跑也能接上。**「长片替换 — 覆盖整段」（Long-form replace）**——一键把整段素材按设定长度（帧或秒）切成连续窗口，最后一段取余量（不足 1 秒的尾巴并入前一段），并把首个窗口的替换设置复制到所有窗口；配合逐窗口导出，单个不满意的窗口可单独重渲染。**修复 masked（inpaint）路径实际未替换主体**：ComfyUI 的掩码采样从 `latent_image + noise` 起步，重绘区域内残留的原片像素会让去噪器「精修原演员」而非生成替换对象，导致输出与源帧几乎逐帧相同（97 帧窗口平均 |diff| 8/255，同窗口 anchor 模式为 51+/255）；现在在送入采样器前清零重绘区域，保留区仍携带原片，背景保持逐像素一致。另修复：**SeedVR2 放大在实机上静默回退首轮**（ComfyUI 执行节点时 `custom_nodes` 不在 `sys.path`）、**显存清理在每个段边界多卸载一次**、**精修失败未点名占用显存的模型**、**外部注意力补丁跳过在面板中不可见**、**Segment 预览在 source/keep 模式静音**、**结果音频改用 Blob URL 播放**（此前 `data:` URL 拖动进度会爆音）。
> - **v1.8.0 新增**：**Global Refine 时间分块（temporal split）**——二段采样过去一次性重采样整段放大后的潜变量，显存占用随序列长度线性上升；现在改为逐块重采样并交叉淡入淡出，峰值显存只受单个块限制，长片因此变得可精修。块长与重叠自动对齐 H3 的 17 帧网格（`temporal_chunk_frames` / `temporal_overlap_frames`），可与**平铺精修**组合（时间外层 + 空间内层），在小显存显卡上两者并用；音频原样透传、不参与重采样。作用范围是刻意的：仅在**无 Motion Context 重锚定且无 H3 噪声掩码**时启用，此时条件对每个块一致、无需逐块重定时间锚。交叉淡入权重逐 token 求和为 1，因此在恒等采样器下拼接是无损的。另新增 **SeedVR2 放大方式**（时序感知的像素空间放大，自带 3B DiT + VAE，首次使用约需下载 6 GB；会先卸载 H3 模型再重载），面板会实时探测该节点是否可导入。**并修复「段间清理显存」看似无效的问题**：清理步骤此前共用一个 `try`，第一步抛错会连带跳过卸载与清缓存；段末清理无条件卸载模型，单段任务会立刻为重载买单；而 ComfyUI 无法卸载的模型（包装器已被回收，`free_memory` 会跳过）只写日志。现在逐步隔离、单段时保留模型，并在节点执行报告中新增 **VRAM** 栏，点名失败步骤或被占用的模型。示例工作流的 `clear_vram_between_segments` 此前为 `false`（与默认值相反），现已改为 `true`。
> - **v1.7.0 新增**：**首轮复用（Reuse cached first pass）**——勾选后首轮 H3 采样的原始 AV 潜变量按「除后期处理外」的指纹写入磁盘，之后用相同 seed / 提示词 / 参考图 / 分辨率、但调整 Global Refine / Face Refine / Audio Room 时可直接跳过首轮采样、只重跑后期（实测 107 帧 r2v 从 363 秒降至 33 秒）；seed / 提示词 / 参考图 / 分辨率 / 采样器 / 模型改变时缓存自动失效。另新增 **平铺精修（tiled refine）**（把 Global Refine 二段采样切成重叠空间块以降低显存占用）、**对比导出（export comparison）**（同时写出 `_raw_firstpass` 与 `_postprocessed` 便于对比）、**外部 patch 时跳过精修（allow_refine_on_external_patch）**，以及**实验性「潜空间接续」（latent_continuation_enabled，早期测试）**——把上一段末尾潜变量直接注入下一段采样流并用嵌套噪声掩码锁定。
> - **v1.5.0 新增**：**Audio Room（逐场景声场）**——后期处理面板新增第三栏，为模型生成的音频加上真实空间感。可选 `bedroom` / `bathroom` / `bar` / `office` / `car` / `hall` / `cathedral` / `outdoor` / `dry` 等预设（一次设定全部六个混响参数），也可选 **Custom** 自行调整混响量、高频衰减、空间尺寸、立体声深度、预延迟与湿声增益；另有独立的**电平**（标准化 / 增益）。每个片段可在时间线的 `room` 字段声明自己的空间，同一支影片里的浴室与卧室不再共用一套声场。该处理在输出组装阶段执行、位于片段音频缓存之后，**不会使任何片段、上下文缓存或已完成渲染失效**；立体声与采样数完整保留，处理失败的音轨保持干声并**在报告中点名**。另新增**共享提示块静音守卫**，以及一批 **Resume 正确性修复**（四个 plan builder 各自漏传 resume 标志、引擎接管起点、预览与音频检查盲区、停止后状态残留）和 **CUDA OOM 被误报为采样器不兼容**的修复。**Audio Room（逐场景声场）**——后期处理面板新增第三栏，为模型生成的音频加上真实空间感。可选 `bedroom` / `bathroom` / `bar` / `office` / `car` / `hall` / `cathedral` / `outdoor` / `dry` 等预设（一次设定全部六个混响参数），也可选 **Custom** 自行调整混响量、高频衰减、空间尺寸、立体声深度、预延迟与湿声增益；另有独立的**电平**（标准化 / 增益）。每个片段可在时间线的 `room` 字段声明自己的空间，同一支影片里的浴室与卧室不再共用一套声场。该处理在输出组装阶段执行、位于片段音频缓存之后，**不会使任何片段、上下文缓存或已完成渲染失效**；立体声与采样数完整保留，处理失败的音轨保持干声并**在报告中点名**。另新增**共享提示块静音守卫**，以及一批 **Resume 正确性修复**（四个 plan builder 各自漏传 resume 标志、引擎接管起点、预览与音频检查盲区、停止后状态残留）和 **CUDA OOM 被误报为采样器不兼容**的修复。
> - **v1.4.0 新增**：**Stop 部分导出**（停止时把已完成片段合成为可用的部分视频，Resume 仍从第一个未完成片段继续）、**时间线撤销/重做**（Ctrl+Z / Ctrl+Shift+Z，输入框内不会抢撤销）、**命名预设**（只保存采样/接续/输出设置，不含片段、提示词与种子）、**多种子 Sweep**（同一项目按不同种子渲染多次对比）、以及 **Validate / Preview prompt / References** 预检工具。
> - **测试与 CI**：`python -m pytest`（1141 个测试，无需 ComfyUI 即可运行）+ 前端 jsdom 测试，CI 见 `.github/workflows/tests.yml`。
> - **示例工作流**：`example_workflows/` 内含可直接运行的 **ref2va** 示例与配套 AI 生成参考图。
>
> 英文详情见 [Improvements in this fork](README.md#-improvements-in-this-fork)；示例默认模型下载见 [Models used by the example workflow](README.md#models-used-by-the-example-workflow-defaults)。

**一个 Director，从单个 MiniMax H3 镜头到完整的多段视频项目。**

下面连结是教学，或者你想先往下看看介绍?

[English](docs/USER_GUIDE.md) | [简体中文](docs/USER_GUIDE_zh.md)

在一个生产界面中完成 `T2V / I2V / FL2V / R2V / V2V / RV2V`，按片段混合不同生成方式，在镜头之间传递画面与生成音频上下文，只重跑需要修改的片段，管理可复用素材，实时预览生成过程，完成后期精修并导出最终视频，而不需要把 ComfyUI 节点图堆成一堵墙。

> 当前版本：**v1.13.0**

<!-- IMAGE SLOT 1
把 Mixed + Selective Run 主截图放到：
docs/images/hero-mixed-selective-run.png
推荐素材：螢幕擷取畫面 2026-08-19 041546.png
-->

![MiniMax H3 Motion Director — Mixed Mode](docs/images/hero-mixed-selective-run.png)

上图展示原生 **Mixed** 时间线：五个片段使用不同生成路径，片段边界可分别控制画面/音频连续性，同时启用 **Selective Run**，只重新生成选中的片段。

---

## 它能做什么

| 功能区域 | Motion Director 提供的能力 |
|---|---|
| **独立生成模式** | `T2V / I2V / FL2V / R2V / V2V / RV2V` |
| **Mixed Mode** | 每个片段可独立选择 `T2V / I2V / FL2V / R2V / Source Video` |
| **Selective Run** | 只重新生成选中的片段，而不是重跑整条时间线 |
| **跨段连续性** | Motion Context、Context Frames、Latent Scale Lock、生成音频延续、Color Re-anchor |
| **Segment Result 复用** | 将前面 Mixed 片段的解码帧复用为后续 I2V / FL2V 输入 |
| **Source Video 工作流** | 独立 V2V / RV2V 管理，以及用于源视频片段边界的 Source Bridge |
| **素材管理** | Common References + 持久化 Material Library，可管理图片、音频、视频与 Prompt |
| **采样** | 内置采样或外接 ComfyUI `SAMPLER + SIGMAS` |
| **后期处理** | Global Refine、放大、可选 NVIDIA RTX VSR / Deblur、Face Refine |
| **预览与输出** | Director Live Preview、Segment / Multi Segment / Final Result、最终视频保存 |
| **ComfyUI 集成** | 外接 `Director Inputs / Director Assets`，以及 `images / audio / fps` 输出 |

Motion Director 本身是 `OUTPUT_NODE`，可以直接作为工作流终点运行，同时仍然把最终画面帧、音频和 FPS 暴露给下游 ComfyUI 节点继续处理。

---

## Live Preview

Motion Director 有自己的实时预览界面，不只依赖普通 sampler preview。工作流运行时可以显示当前生成阶段，也能继续显示后续后处理阶段。

<!-- IMAGE SLOT 2
把 Live Preview GIF 放到：
docs/images/live-preview.gif
推荐素材：Video Project 1(1).gif
-->

![MiniMax H3 Motion Director — Live Preview](docs/images/live-preview.gif)

---

## Mixed Mode：在同一条时间线混合不同生成方式

普通 H3 工作流通常把每次生成当成独立片段。Mixed Mode 则把整个项目当成一条时间线。

例如：

```text
S1  T2V
S2  I2V
S3  R2V
S4  Source Video
S5  T2V
```

每个片段都有自己的模式、Prompt、时长或 Source Range，以及当前模式允许使用的媒体输入。

### Mixed 片段模式

| Mixed 片段模式 | 运行路径 | 主要用途 |
|---|---|---|
| `T2V` | T2V | 文本驱动镜头 |
| `I2V` | I2V | 从上传图片或前面 Segment Result 开始生成 |
| `FL2V` | FL2V | 控制首帧、尾帧或两者 |
| `R2V` | R2V | 人物 / 场景 / 动作 / 声音参考 |
| `Source Video` | V2V 或 RV2V | 使用源视频动作，并可额外加入人物参考图 |

`Source Video` 在 Mixed 中故意只保留一个模式：

```text
Source Video + 0 张 Identity Pictures  -> V2V
Source Video + Identity Pictures       -> RV2V
```

Source Video 属于当前片段本身。`Start sec` 和 `End sec` 定义 Source Range，所选范围直接决定这个片段的时长。

### 按片段边界控制连续性

Mixed 可以直接在两个片段卡片之间决定是否请求连续性：

```text
[S1]  S1 -> S2  [S2]  S2 -> S3  [S3]
        visual          visual
        audio           audio
```

主节点上的连续性设置仍然是全局总开关，因此可以让某些边界继续继承，也可以让另一些边界主动重置。

### Segment Result

Mixed Mode 可以把前面已经生成完成的片段解码成静态帧，再给后面的片段使用：

```text
Earlier Segment -> last frame
Earlier Segment -> explicit frame index
```

常见用途：

- 前面片段 -> I2V 起始图
- 前面片段 -> FL2V 首帧
- 前面片段 -> FL2V 尾帧

Segment Result 是静态帧引用，与 Motion Context 是两套独立机制；模式允许时，两者可以同时使用。

### Selective Run

长项目通常不需要每次把所有镜头重新生成。启用 **Selective Run** 后，只勾选需要再跑一次的片段；其余片段在已有缓存或可用源结果时保持不变。

这也是 Director 存在的核心原因之一：修 Shot 3，不应该自动意味着 Shot 1、2、4、5 全部重新付一次生成成本。

---

## 独立 H3 模式

同一个 Director 也支持六种独立 MiniMax H3 任务模式。

| 模式 | 主要输入 | 典型用途 |
|---|---|---|
| `T2V` | Prompt | 文本驱动的多镜头生成 |
| `I2V` | Prompt + 起始图 | 让人物图或场景图动起来 |
| `FL2V` | Prompt + 首帧/尾帧 | 明确控制镜头起点和终点 |
| `R2V` | Prompt + 多模态参考 | 人物、风格、动作、场景、声音或物体参考 |
| `V2V` | Source Video + Prompt | 保留源动作/内容结构并重新生成画面 |
| `RV2V` | Source Video + Prompt + 参考素材 | 源视频动作 + 人物/音频参考 |

R2V 的每个 Assets 组最多可以包含：

```text
Picture 1-9
Video 1-3
Audio 1-3
```

独立 V2V / RV2V 使用 Director 专用的 Source Video 工作流。对于符合条件的源视频分段边界，Source Bridge 可以重新生成一小段过渡，而不是把分段只当成硬切。

---

## Common References

Common References 是项目级共享素材，可以让多个独立片段共同使用。适合重复出现的人物、场景、道具、动作参考和音频，不需要每段都重新添加一次。

<!-- IMAGE SLOT 3
把 Common References 截图放到：
docs/images/common-references.png
推荐素材：螢幕擷取畫面 2026-08-19 040543(1).png
-->

![MiniMax H3 Motion Director — Common References](docs/images/common-references.png)

片段专属素材仍然只属于当前片段/组。执行时，Common References 与本段素材会组合成当前任务真正使用的参考序列。

---

## Material Library

持久化 **Material Library** 用来保存希望跨镜头、跨项目重复使用的素材。

可保存：

- 图片
- 音频
- 视频
- Prompt

图片可以按人物、场景、道具或其他类型分类。搜索和分配都直接在 Director UI 中完成，不需要每次重新从硬盘寻找同一份素材。

<!-- IMAGE SLOT 4
把 Material Library 截图放到：
docs/images/material-library.png
推荐素材：螢幕擷取畫面 2026-08-19 035702(1).png
-->

![MiniMax H3 Motion Director — Material Library](docs/images/material-library.png)

在 Mixed Mode 中，素材库会作用于当前选中的片段，并且只显示该片段模式允许使用的素材。真正的 Mixed `Source Video` 仍然是本地上传，不会把素材库里的 Reference Video 当成源视频。

---

## 后期处理

Director 不只负责第一遍生成，也可以继续处理后期，不需要每个项目都额外搭一套后处理节点图。

<!-- IMAGE SLOT 5
把 Postprocess 截图放到：
docs/images/postprocess.png
推荐素材：螢幕擷取畫面 2026-08-19 034623(1).png
-->

![MiniMax H3 Motion Director — Postprocess](docs/images/postprocess.png)

### Global Refine

Global Refine 可以运行第二遍采样，并可在精修前对片段/结果进行放大。

根据当前安装的运行环境和模型，可使用的路径包括：

- 普通 resize / upscale
- ComfyUI upscale models
- NVIDIA RTX Video Super Resolution
- NVIDIA RTX Deblur
- 第二遍 H3 sampling / refinement

如果 Global Refine 失败，Director 会保留已经完成的第一遍结果，而不是把整个生成结果丢掉。

### Face Refine

Face Refine 提供集成的人脸修复路径，包括：

- 人脸检测与追踪
- 基于 crop 的 H3 再生成
- 自适应 refine strength
- mask / stitch 控制
- color matching

如果没有检测到可用人脸，或 Face Refine 本身失败，会保留已经组装完成的原结果作为 fallback。

---

## Results：Segment、Multi Segment、Final Result

结果直接在 Director 内管理，而不是最后只得到一个没有上下文的输出 batch。

<!-- IMAGE SLOT 6
把 Results 截图放到：
docs/images/results-final.png
推荐素材：螢幕擷取畫面 2026-08-19 035629(1).png
-->

![MiniMax H3 Motion Director — Final Result](docs/images/results-final.png)

Results 页面分为三层：

- **Segment** — 检查单个生成片段
- **Multi Segment** — 预览/导出一个连续片段区间
- **Final Result** — 检查并保存完整最终结果

Final 页面还提供视频保存设置和 Director Report。Report 会记录真实运行配置、连续性状态、采样信息以及后处理状态。

公开节点输出保持简单：

| 输出 | 类型 | 说明 |
|---|---|---|
| `images` | `IMAGE` list | 最终生成视频帧 |
| `audio` | `AUDIO` list | 对应最终音频 |
| `fps` | `FLOAT` | 最终帧率 |

---

## 外接 Director Inputs / Assets

Director 是一体化生产界面，但不是封闭黑盒。其他 ComfyUI 节点仍然可以通过外接输入架构，把 Prompt 和媒体传入独立模式。

<!-- IMAGE SLOT 7
把 External Inputs / Assets 节点截图放到：
docs/images/external-inputs.png
推荐素材：螢幕擷取畫面 2026-08-19 040419(1).png
-->

![MiniMax H3 Motion Director — External Inputs and Assets](docs/images/external-inputs.png)

```text
MiniMax H3 Motion Director Assets
        ↓
MiniMax H3 Motion Director Inputs
        ↓
MiniMax H3 Motion Director
```

仓库提供三个 Director 相关节点：

| 节点 | 用途 |
|---|---|
| `MiniMax H3 Motion Director` | 主 UI、执行、连续性、预览、后处理与结果管理 |
| `MiniMax H3 Motion Director Inputs` | 动态 Prompt / image / Assets 输入 |
| `MiniMax H3 Motion Director Assets` | 打包当前输入组所需的模式专属媒体 |

独立模式的外接输入形状：

```text
T2V   prompt_N
I2V   image_prompt_N + image_N
FL2V  fl_prompt_N + fl_assets_N
R2V   ref_prompt_N + ref_assets_N
RV2V  rv_prompt_N + rv_assets_N
V2V   Source Video 由 Director 管理
```

Mixed v1 使用原生 Director 时间线/媒体 UI，不走外接 group 系统。

---

## 采样与性能

Motion Director 可以使用内置 sampler 设置，也可以接入外部 ComfyUI 采样链。

同时连接：

```text
SAMPLER
SIGMAS
```

Director 就会使用外部采样；否则使用内部 sampler、scheduler、step 数、Video Sigma Shift 和 Audio Sigma Shift。

对于较长任务，**Clear VRAM Between Segments** 可以在片段之间释放模型/缓存，降低显存压力。它是用部分速度换取更低显存占用的稳定性选项，不是性能加速选项。

---

## 安装

### ComfyUI-Manager / Comfy Registry

搜索：

```text
MiniMax H3 Motion Director
```

### 手动安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/j955229/ComfyUI-MiniMax-H3-Motion-Director.git
cd ComfyUI-MiniMax-H3-Motion-Director
python -m pip install -r requirements.txt
```

如果使用 Windows portable 版本，请使用该 ComfyUI 实际使用的 Python 可执行文件来运行 `pip`。

安装后请完整重启 ComfyUI。如果更新包含前端文件，也请完整重启 ComfyUI 并 hard refresh 浏览器。

---

## 要求 / 兼容性

Motion Director 需要**较新的、已经包含官方 MiniMax H3 支持的 ComfyUI 版本**，其中包括当前运行路径依赖的官方 MiniMax H3 conditioning 节点。

核心 Python 依赖已写入项目 package / requirements 文件。部分后处理功能还有额外可选依赖，例如：

- NVIDIA RTX VSR / Deblur 需要兼容的 NVIDIA VFX runtime/package 和支持的 NVIDIA 硬件
- Face Refine detector / SAM 路径需要 UI 中选择的相应 detector/model 依赖
- Upscale Model 模式需要兼容的 ComfyUI upscale model

对于可选后处理阶段，Director 的设计目标是在该阶段无法运行时保留前面已经可用的结果。

> 不要同时加载独立版 `ComfyUI-H3-Motion-Context`。Motion Context 兼容逻辑已经集成到 Motion Director 中。

---

## Mixed v1 说明

- Mixed v1 使用原生 Director UI 管理媒体，不使用外接 `Director Inputs` group。
- Mixed `Source Video` 只能本地上传；Material Library 中的视频是 Reference Video，不是实际 Source Video。
- Source Bridge 是独立 V2V / RV2V 功能，Mixed v1 不使用 Source Bridge。
- Segment Result 只能向前引用：后面的片段可以复用前面结果，不能引用未来片段。
- 连续性功能可以改善跨段衔接，但不保证每次生成都得到完全不可见的边界；MiniMax H3 本身仍可能产生画面、动作、光照或人物一致性漂移。

---

## Credits / 上游项目

Motion Director 本身就是一个集成型项目。它明确包含、修改或参考了多个现有 ComfyUI H3 项目的代码/算法，而不是把所有组件都包装成“从零独立发明”。

- [AIMixer / ComfyUI_MiniMaxH3_Director](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director) — Apache-2.0
- [NikoDemon80 / ComfyUI-H3-Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context) — GPL-3.0
- [Carasibana / ComfyUI-H3-FaceRefine](https://github.com/Carasibana/ComfyUI-H3-FaceRefine) — MIT
- [Kijai / ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) — GPL-3.0；部分 packed-latent preview / TAEHV 行为参考其实现

感谢所有上游作者和贡献者。

准确的第三方署名和派生说明见 [`NOTICE`](NOTICE)、[`LICENSE`](LICENSE) 和 [`LICENSES`](LICENSES)。

## License

本项目整体以 **GNU GPL v3.0** 发布。
