# Garment Studio 技术方案 v1

> 面向"个人设计师可用 + 可改可删"的 ChatGarment 复现分支。
> 状态：v1 已定稿方向，M0 核心管线已跑通（见 §9）。作者与用户共同确认。

## 1. 目标与非目标

**目标**：一条不依赖 8 GB 显存、不依赖 VLM 的可用流程——
图片 → 文字描述（人可改）→ 设计 JSON → GCrc 纸样 → 3D 网格包 →（Blender 垂坠预览）。

**非目标（v1 明确不做）**：
- 不做训练、不跑 VLM 权重、不用官方数字头（数字由模型估计 + 人给滑杆，见附录 A）。
- 不打包 Blender addon（先保证全流程可用，测试通过后再讨论打包）。
- 不做 SVG 版片回读（只交出只读 SVG，回读放到 v2）。
- 不引入注册表写入 / 全局 Python 包 / 全局 PATH 改动。

## 2. 三个角色

| 角色 | 谁 | 干什么 | 在哪 |
|---|---|---|---|
| 大脑 | DSH 里的模型 | 看图写描述、写 design.json、调 CLI、报结果 | 聊天里 |
| 审批面 | studio 面板 | 显示描述与产物、让人改字并确认、把确认送回聊天 | 侧栏 iframe / 浏览器 |
| 手脚 | studio CLI | design.json → 纸样 → OBJ 包（确定性、无模型） | 后台 subprocess |

关键：**面板不是聊天窗口**。它只做"显示 / 改字 / 按确定"，模型调用一律通过聊天完成。

## 3. 流程（交接式，不阻塞）

```
① 人在聊天里拖入图片 + 说"做一件抹胸短裙"
② 模型把图片缓存进 workspace/jobs/<id>/input.png，写 request.json
③ 模型看图，写 description.txt（纯文字，人类语言）→ 结束本轮
④ 面板显示 input.png + description.txt 文本域 +【确定】【修改→确定】
⑤ 面板写 approval.json，并向聊天投一条短消息："[garment] <id> 描述已确认，请继续"
⑥ 模型读 approval.json 的文本（不用消息里的转述，避免走样）
⑦ 模型写 design.json（garment 结构 + 命名浮点）
⑧ 模型调 `studio.core.cli build` → package（manifest/sidecar/pattern/mesh）
⑨ 面板轮询到 package 完成 → 显示 2D 纸样、预览图、按钮【打开文件夹】【仿真】
```

- 步骤③结束本轮 = 不阻塞，人看多久都行；聊天里留下"我确认了这版描述"的天然审计痕迹。
- 面板投消息靠 DSH 宿主 API `sessionController.prompt`；sessionId 由模型写进 request.json。
- 开发期没有 DSH 宿主时，面板由 `python -m studio.server` 起本地服务，"投消息"降级为写 `inbox/pending.json`，模型下次读它。

## 4. job 目录协议（唯一的接口契约）

```
studio/jobs/<job_id>/            # job_id = 20261106-1328-dress
  request.json     # {id, image, instruction, sessionId, createdAt, stage}
  input.png        # 从聊天附件复制来的图（可删，不影响重建）
  description.txt  # 模型写（③）
  approval.json    # 面板写 {decision:"accept"|"edit", text, at}（⑤）
  design.json      # 模型写（⑦）
  package/         # CLI 产出（⑧）
    manifest.json  sidecar.json  design.json
    pattern/       mesh/
  log.txt          # CLI stdout/stderr，排错用
  result.json      # 模型写 {ok, package, message}
```

stage 取值：`created → described → approved → designed → built → failed`。
谁写哪个文件是硬规矩：模型只写 request/description/design/result，面板只写 approval，CLI 只写 package/log。

## 5. 目录树（全部在 ChatGarment-main/ 下，删目录即卸载）

```
studio/
  core/      paths.py design.py build.py cli.py      命令行核心（已完成 M0）
  panel/     index.html app.js style.css             审批面（M1）
  server.py  开发期 HTTP 服务 + jobs API（M1）
  sim/       cloth_setup.py runner.py                Blender headless 仿真（M2）
  jobs/      运行时 job 目录（可整体删除）
  runs/      冒烟/历史产物（可整体删除）
  README.md
```
DSH 插件（M3，另目录）`dsh-plugin/garment-studio/`：宿主路由把 `studio/panel` 服务出去 + 侧栏 iframe + 一条 `sessionController.prompt`。安装 = `dsh plugin add link:` + cordis.patch.yml 一条 insert；卸载 = 删目录 + 删条目。

## 6. CLI 契约（已完成 M0）

```bash
./.venv/Scripts/python.exe -m studio.core.cli paths --design D.json   # 打印该设计需要填的浮点路径
./.venv/Scripts/python.exe -m studio.core.cli build --design D.json --out studio/jobs/<id>/package --tag <id>
```
- 退出码：0 成功 / 2 design 文件本身有问题（缺字段、浮点名写错、超 [0,1]）/ 3 GCrc 拒绝该参数组合。
- 错误信息必须能指导下一步动作（缺哪些浮点名、哪些浮点越界、为什么被拒）。
- 实测耗时：15.5 s（纸样 3.5 s + 网格 12 s），纯 CPU。

design.json 格式：
```json
{"schema": "gcstudio/design/1", "label": "抹胸短裙",
 "garment": {"wholebody_garment": {"meta": {...}, "shirt": {"length": null, ...}, ...}},
 "floats": {"design.shirt.length": 0.20, ...}}
```
- 占位用 `null`（真实 JSON，能被人手改、能被编辑器校验）。
- **浮点用命名键**，不用位置数组：顺序由 `ordered_float_paths_from_pred()` 从文本结构推出，模型写错名字会被当场指出；同一套键天然就是滑杆的分组（M1 直接拿来渲染滑块）。

## 7. 面板 API（M1）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | /api/jobs | job 列表（id、stage、label、缩略图） |
| GET | /api/jobs/&lt;id&gt; | 单 job 详情（含 approval 状态） |
| POST | /api/jobs/&lt;id&gt;/approve | {decision, text} → 写 approval.json + 投消息 |
| GET | /api/jobs/&lt;id&gt;/file?p=... | 只允许 job 目录内的相对路径（防穿越） |
| POST | /api/jobs/&lt;id&gt;/open | 在资源管理器打开产物目录；返回 `{ok, method, path, error}`（失败时面板据此复制路径/请宿主代开） |
| GET | /panel | 页面本身 |

## 8. 质量门（每一步都要能说是"可用"）

1. **design.json 校验**：schema、部件形状、浮点名齐全、范围 [0,1]。
2. **纸样合法性**：GCrc 自己会拒（`_safe_try_generate`），被拒时把 design.yaml 与原因回给模型 → 微调重试一次。
3. **网格合理性**：顶点/面数 > 0、bbox 合理（高 60–200 cm）、面数 < 200k。
4. **仿真稳定性（M2）**：跑到 60 帧不炸（无 NaN、无顶点飞到 1e4 外）；炸了自动降 Quality Steps / 缩小时间步重试一次。
5. **产物可打开**：glb 能被 Windows 3D 查看器打开（M2 验收）。

## 9. 里程碑与状态

| 里程碑 | 内容 | 验收 | 状态 |
|---|---|---|---|
| M0 | core：design.json → package | `cases/rc_dress/design.json` 复现出与 bypass 相同纸样/网格，15 s 内 | **已完成**（2026-11-06） |
| M1 | 面板 + job 协议 + 审批回投 | 浏览器里完成"看图→改字→确定→产物出现"一圈 | **已完成**（2026-11-06） |
| M2 | Blender headless 垂坠 + 预览 | headless 跑出穿上身的 glb + 渲染图，60 帧不炸 | **已完成**（无袖款；有袖为已知限制） |
| M3 | DSH 插件壳 + 图片缓存闭环 | 侧栏里全套跑通；模型从聊天收到图自动缓存 | **代码完成**，待重启 DSH 挂载验收 |
| M4 | 打包 addon / SVG 回读 / 批量 | 按需 | 后置 |

M0 实测数据：rc_dress 抹胸短裙，6 片裁片（right/left btorso+ftorso、skirt front/back），6897 顶点 / 13512 面 / 26 条缝线，bbox 高 58.9 cm，耗时 15.5 s。

### 9.1 实测数据（2026-11-06）

| 用例 | 规模 | 纸样 | 仿真 | 结论 |
|---|---|---|---|---|
| rc_dress 抹胸短裙（7 浮点） | 6897 顶点 / 26 缝线 | 10.3 s | bake 61.4 s（quality 8 / 96 帧） | 可用：合身抹胸、裙摆有褶 |
| T恤+及踝长裙（19 浮点，有袖） | 24238 顶点 / 46 缝线 | 18.1 s | bake 130.7 s（quality 6 / 72 帧，重网格自动降档） | 可用：短袖卷在手臂上、裙摆垂到脚踝（袖口偏蓬，见 11.1） |
| 三层蛋糕短裙（FittedShirt + SkirtLevels×3，无袖） | 13076 顶点 / 38 缝线 | 12.4 s | bake 243.5 s（quality 8 / 96 帧） | 结构对（三层荷叶边都在）但**太长**：落到实处是及踝，见 11.1 第 7 条 |
| 同上改 Skirt2 高抽褶（最终交付的版本） | 6473 顶点 / 26 缝线 | 12.4 s | bake 38.2 s（quality 8 / 96 帧） | 可用：抹胸贴体 + 抽褶 A 字迷你裙，下摆到大腿中段 |
| 验收①针织衫+格纹短裙（19 浮点，长袖 CuffBand） | 10122 顶点 / 46 缝线 | 18.3 s | bake 66.8 s（quality 6 / 72 帧，自动降档） | 勉强：裙形对，长袖被压成贴臂的扁片、肩部有锯齿翻片 → 只适合当草稿（见 11.1 第 1 条） |
| 验收②条纹短袖+大摆中长裙（19 浮点，CuffSkirt） | 18171 顶点 / 46 缝线 | 16.1 s | bake 79–82 s（quality 6 / 72 帧，自动降档） | 可用：A 字中长裙竖褶到小腿、短袖卷在臂上；肩部仍有锯齿边 |
| 用户图③黑T+白A字及膝裙（19 浮点，短袖 CuffBand） | 16216 顶点 / 44 缝线 | 15.4 s | bake 55.2 s（quality 6 / 72 帧，自动降档） | 大体可用：合体圆领短袖 + A 字及膝裙、有竖向褶皱；袖子肩部与腰头各有一处褶堆（见 11.1 第 1 条） |

产物：`studio/jobs/<job>/package/{pattern,mesh,sim}`，glb 1.1–1.7 MB；另外每次仿真会写 `sim/sim_drape.blend`
（带 Cloth 修改器 + 已烘点缓存 + 身体/地板，15.3 MB），供人直接在 Blender 里打开改。
面板截图 `studio/runs/panel_shot2.png`、`studio/runs/panel_shot7.png`；验收两张：`studio/runs/panel_accept.png`（面板，含 hero 作业）与 `studio/runs/blender_accept.png`（Blender 侧栏 `GC Studio` + 已垂坠的两件网格）。

### 9.2 稳定性措施（M2 期间补上）

1. **钉点**：腰缝（下装↔上衣缝线）+ 躯干裁片开口上沿，共 286–300 点（4.1–12%）；钉住的点吸附到皮肤外 1 cm，否则上沿悬空成「漏斗领」。
2. **wrap（wrap-to-body，缩放到身体尺度）**：GCrc 的 BoxMesh 把人台当成约 2 倍大的盒子，布料靠重力在几秒内收不回来 → 先把网格在 x/y 上乘一个统一比例压到身体尺度。比例尺必须取**躯干裁片**的宽度（groups.json 里带 torso 的片），不能取整件 bbox：蛋糕裙在盒子里有 1.7 m 宽，用 bbox 算出的 kx=0.21 会把上身压成 14 cm 的竖条、把每层裙摆压成一条带子（实测正面只剩一条竖缝）；用躯干片（52.6 cm）算出 kx=0.68 后，上身贴身、裙摆保留 2.6 倍抽褶量。体宽取「腰以上 40 cm 高度带的中位数」而不是逐带 98 分位（A-pose 手臂会污染某几带，相邻顶点 kx 差 1.9 倍、边被拉开 10 倍）。**不要做按高度分段的比例尺**：试过腰以上/腰以下分开缩放，长裙被压到小腿宽、跨腰的边被拉 6 倍。改完后三个用例的初始拉伸都是 p99 ≈1.0x、max ≤2.6x、超过 3x 的边 0 条。
**裙子另做一步 `restore_skirt_flare()`**：统一缩放对身体是对的，对抽褶裙是错的——裙摆被缩到胯宽后，褶子只能互相叠住、整条裙子贴着腿（实测一条完整的 A 字裙出来是直筒）。做法是腰部以下 25 cm 内把压缩量线性退回 1.0（腰部系数不变，所以焊死的腰缝不会被撕），裙摆保留它在布局盒里的宽度。验收作业（黑 T + A 字裙）加上这一步后，裙摆从贴腿变成明显的 A 字、还能看到竖向褶皱。
3. **袖子（v2 已落地）**：袖片先排除在 x/y 压缩之外，再按手臂柱面卷起来——对每侧用主成分分析拟合手臂轴线 + 3 cm 分带的中位半径表，把袖片顶点按 (沿臂距离 t, 绕臂角度 θ) 映射到半径 r 的柱面上。三个关键点：① 左右各用**一个共同的坐标系**（否则缝线两端顶点映射到不同位置，缝边被拉 12 倍直接炸）；② 弧长 r 要保证卷起来的弧 **不超过 170°**（超过就自我重叠，两层布互相排斥，5–10 帧内炸到几十米）；③ t 夹在实测臂长范围内（袖片会伸到脖子/头里）。炸掉的两个反面证据：bbox reach 88–144 m。
4. **爆炸守卫**：bake 后若 bbox 任一分量 > 5 m，判 `exploded=true`、`ok=false`，job_runner 抛错并以退出码 4 结束，面板不会把烂网格当成果展示。
5. **重网格自动降档**：顶点 > 15000 时 frames ≤ 72、quality ≤ 6（24k 顶点在 quality 8 下要几分钟）。
6. **超时**：单次仿真 1200 s，超时给出「降 quality / 减裁片」的提示。
7. **交付一个可在 Blender 里打开的工程**：`--save-blend` 写 `<out>/<tag>_drape.blend`（`save_as_mainfile(compress=True)`），job_runner 默认打开它，结果里记 `steps.sim.blend`。实测重开该文件：`body`(23752 顶点, COLLISION) + `floor` + `garment`(CLOTH, pin 组 `pin`, 缓存 1..96 已烘)。失败不影响 glb（try/except 记 `blend_error`）。
8. **「打开文件夹」的失败可见、可降级**：`open_folder()` 依次尝试 `os.startfile` → `explorer.exe <path>` → `xdg-open`，返回 `(ok, method, error)`；路由永远 200，面板据 `ok` 决定提示「已打开」还是「失败原因 + 复制路径」。**限制**：若服务进程起在沙箱/后台会话（无 window station），GUI 启动一定被系统拒绝——实测 `startfile` 报 `WinError 5`、`explorer.exe` 退出码 `3221225794 (0xC0000142)`，`cmd /c start` 退出码 1；此时面板嵌在 DSH 里会再走宿主 postMessage 中转（宿主在用户桌面会话），仍不行就把路径塞进剪贴板。要原生可用：双击 `win/studio.bat` 由用户桌面起服务。
9. **glb 必须导"垂坠后的静态网格"**：`export_scene.gltf` 写文件时会重新求值依赖图，对已烘布料的 Cloth 对象可能取到第 1 帧 → 导出的 glb 是**未仿真的平板盒子**（症状：面板上的三视图是对的，但在 Blender 里打开 glb 是方块；用 trimesh 量顶点与 `sim.json` 的 `garment_bbox_after` 对不上即可确诊）。修法：新增 `static_copy()`，用 `bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))` 把当前帧烘好的几何拷成无修改器的新对象，只选这两个对象导出、`export_apply=False`，导出后 `finally` 删掉拷贝。复核：导入后对象名 `sim_garment_drape`（18171 顶点，z 0.34–1.49 m），headless 渲染确认是真垂坠。

## 10. 可删性清单

- 删 `studio/`（全部代码与运行产物）、`dsh-plugin/garment-studio/`、`cordis.patch.yml` 里那条 insert、`~\.dsh\profiles\web\node_modules\dsh-garment-studio` 软链 = 完整卸载；
- 若装过 Blender 插件：偏好设置里取消勾选 + 删 `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\gcstudio\`（`install.ps1 -Uninstall` 与 `win/cleanup.ps1` 都会处理这两处）。
- 本方案不写注册表、不改 PATH、不装全局包、不碰 D:\ChatGarment_data 以外的用户目录。
- 已有 `win/cleanup.ps1` 可清掉最初复现留下的 .venv / .tmp / repos / runs / checkpoints / assets junction；studio 是独立增量，两者互不依赖。

## 11. 已解决的问题 / 已知限制 / 未决

已解决（都有实测记录）：

1. Blender 5.2 cloth 属性名已 dump 并落地（`studio/sim/probe_blender.py` → `probe_result.json`）；pin 顶点组的真名是 `settings.vertex_group_mass`，不是 `vertex_group_pin`。
2. OBJ 缝合顶点已焊接：6897 顶点、重复顶点 0、开放边 282（全是领口/下摆/袖窿），所以**不需要** Blender sewing springs，cloth + pin + 碰撞就够。
3. skill 以 `docs/GC_STUDIO_SKILL.md` + `studio/agent.py` CLI 形式交付，模型照文档执行即可，不必注册成 DSH skill。
4. **袖子不会再炸了**（v2）。袖片排除压缩 → 拟合手臂轴线 → 卷成柱面（共同坐标系 + 弧 ≤170° + t 夹在臂长内），tee+长裙 24238 顶点 bake 130 s 后 bbox 稳定在 x±0.42 / y±0.16 / z 0.05–1.46 m，连续 4 次不同参数（q4/q5、30/48/72 帧、冻结/自由袖子）都没有再出现爆炸。
5. **「打开文件夹」不再是黑盒**（详见 9.2 第 8 条）：错误被上报并降级为复制路径；同时能产出 `.blend` 工程，人可以脱离面板直接在 Blender 里看/改（9.2 第 7 条）。
6. **glb 里现在是垂坠后的衣服**（详见 9.2 第 9 条）：导出前把求值结果冻成静态网格，`sim_garment_drape` 18171 顶点 z 0.34–1.49 m 与 `sim.json` 一致。
7. **Blender 侧栏插件已交付**：`studio/blender_addon/`（`bl_info` 传统插件，2026-11 在 Blender 5.2.4 LTS RC 上实测），打包 `dist/gcstudio-0.1.0.zip`。面板在 3D 视图右侧 `GC Studio`，四个按钮：生成纸样 / 布料仿真 / 载入结果 / 打开输出文件夹，状态行 + 最近日志。它不算几何，只调仓库命令行（`studio.core.cli build` 与 `blender -b --python studio/sim/cloth_setup.py`）再把 `sim.glb` 导进当前场景，因此与 CLI 行为永远一致；因为 Blender UI 单线程，作业在子进程里跑、面板只轮询。headless 安装 + 端到端（build→sim→load）测试脚本：`studio/blender_addon/_test_install.py` / `_test_flow.py`；UI 截图脚本 `_shot_accept.py`（启动 splash 会挡住视口，需先 `preferences.view.show_splash=False` 并保存偏好）。

### 11.1 已知限制（v1 有意留在外面）

1. **袖子只是"大概对"**。柱面吸附把袖片卷在手臂上、不再塌，但半径取 max(臂半径, 弧长/170°) 常常偏大，袖口会蓬、褶子偏碎；袖窿环仍不钉（钉上会自我折叠并炸），所以袖山靠躯干上沿的拉伸撑着。要进一步做需按袖窿弧长解半径、把袖窿环钉到手臂表面。
2. **只支持整件式**（`wholebody_garment`）。上下装拆分的 design.json 会被 `design.validate()` 明确拒绝并给出改法，因为 GCrc 会出两份 specification.json，而 v1 只取第一份 → 下半身会被静默丢弃（实测过）。
3. **浮点必须是人给的**。官方数字投影层在本机 4-bit 下对任意文本都给贴边界的荒谬值且不报错，所以产品的数字来自模型给 5–8 个关键值 + 滑杆微调 + 中位数兜底，回归器只当可选实验。
4. **没有材质/颜色/纹理**。GCrc 的表示里没有这些，面板只做形状。
5. **Blender 侧没有 Python PIL**：三视图拼图在 venv 里做（`job_runner.stitch_views`）。
6. 单次仿真 60–330 s，取决于顶点数与 quality；改设计要重算纸样 + 重仿真（参数级缓存留到 M4）。
7. **GCrc 的“蛋糕裙”（SkirtLevels）做不了迷你长度**。它的结构是 base 裙 + 每层 10 cm 的固定荷叶边，最短配置（length 0、base_length_frac 0.2、3 层）在盒子里就已经从腰到 38 cm，垂坠后到脚踝；2 层也只到膝。要迷你 + 荷叶边只能用 Skirt2/SkirtCircle 的 ruffle 做“高抽褶”近似（交付版本即如此），代价是丢掉层次接缝。

### 11.2 未决

1. 图片附件路径是否稳定可复制（DSH 侧栏插件待重启验收）；不稳就在面板加「上传」通道。
2. 2D 版片（SVG）回读成可编辑版片：目前只交只读 SVG，回读路径后置（+1 天）。
