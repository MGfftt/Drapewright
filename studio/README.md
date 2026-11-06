# studio/ —— GCrc 造衣管线（v1）

不依赖 VLM、不依赖 8 GB 显存的一条完整流程：

    图片 → 文字描述（人可改） → design.json（浮点由模型给） → GarmentCodeRC 纸样
         → 3D 网格包（OBJ + sidecar） → Blender headless 布料垂坠 → glb + 三视图

## 快速开始

    cd ChatGarment-main

    # 1) 只造纸样 + 网格（≈10-16 s，不需要 Blender）
    ./.venv/Scripts/python.exe -m studio.core.cli build \
        --design cases/rc_dress/design.json --out studio/runs/demo --tag demo

    # 2) 造 + 垂坠仿真（≈1-4 min，需要 Blender 5.x）
    ./.venv/Scripts/python.exe -m studio.agent new --image <图片> --title "抹胸短裙"
    ./.venv/Scripts/python.exe -m studio.agent describe <job_id> --file desc.txt
    ./.venv/Scripts/python.exe -m studio.agent run <job_id> --frames 96 --quality 8

    # 3) 人在浏览器里审 / 改 / 确认
    ./.venv/Scripts/python.exe -m studio.server --port 8765 --open
    #    （推荐）Windows 上直接双击 win/studio.bat：它清掉旧进程、用你自己的桌面会话
    #    起服务并开浏览器，这样面板里的「打开文件夹」才真的能弹出资源管理器。

## 文件

| 路径 | 作用 |
|---|---|
| core/paths.py | 命名浮点 → GCrc 有序向量（顺序从 design_used.yaml 推出，不猜） |
| core/design.py | design.json 的加载与校验（只允许整件式，见下） |
| core/build.py | design → 纸样 → OBJ + sidecar.json + manifest.json |
| core/cli.py | `build` / `paths` 命令行 |
| agent.py | 模型侧 CLI：new / describe / template / wait / run / show / list |
| job_runner.py | 一个 job 的 build + Blender 仿真 + 三视图拼图 |
| jobs.py | job 目录协议（request/description/approval/design/package/log/result） |
| server.py | 纯 stdlib 的本地 HTTP 服务 + jobs API（面板后端） |
| panel/ | 深色单页面板：输入图、描述文本域、确认按钮、产物卡片、日志 |
| sim/cloth_setup.py | Blender 内：导入包 → 包裹到人体 → 钉合 → 布料求解 → glb + 渲染 |
| sim/check_mesh.py | OBJ 连通性检查（缝合顶点是否已焊接） |
| dsh-plugin/ | DSH 侧栏插件（把面板放进 DSH 侧栏，并把确认回投到聊天） |

## 产物

    package/
      manifest.json   产物清单（谁生成、有哪些文件）
      sidecar.json    网格事实：单位、bbox、顶点/面/缝线数、裁片、浮点、groups 路径
      design.json     输入的设计（可复现）
      pattern/        specification.json + 纸样 PNG/SVG（人可改、可打印）
      mesh/           <tag>_garment.obj, <tag>_body.obj, <tag>_preview.png, <tag>_groups.json
      sim/            sim.glb, sim_drape.blend, sim_front/side/back.png,
                      sim_views.png, sim.json

## 在 Blender 里看结果

每次仿真除了 `sim.glb`，还会写一个 **`sim_drape.blend`**（Blender 工程，约为 glb 的 10 倍大，
因为带了解算后的点缓存）：身体 + 衣服 + 地板都在，衣服上保留着 Cloth 修改器、Pin 顶点组和已烘好的帧缓存。

两种打开方式：

1. **双击 .blend**（或在 Blender 里 `File → Open`）→ 直接看到垂坠后的结果；
   `Scene Collection` 里 `body` 是人体、`garment` 是衣服；空格播放能看到 1..96 帧的解算缓存；
   选中 `garment` → 右侧扳手图标能看到 Cloth 参数，改质量/刚度后按 `Ctrl+Space` 重算。
2. **只想要一个轻量模型**：`File → Import → glTF 2.0 (.glb)` 选 `sim.glb`（1–2 MB，只有最终一帧，
   没有 Cloth 修改器）。给别的软件/网页用这个。

Blender 平时只是被当成"命令行求解器"调用（`blender.exe -b --python studio/sim/cloth_setup.py`）；
如果想让 Blender 里也有一个面板，装下面那个可选插件即可（不装也能用整条管线）。
## Blender 侧栏插件（gcstudio）

`studio/blender_addon/` 里是一个标准的 Blender 插件（一个侧栏面板 + 4 个按钮），它**自己不算东西**：
只把仓库里的管线当命令调用，再把结果导进当前场景。所以它永远和 CLI 的行为一致。

安装（一次性，30 秒）：

1. Blender → `编辑 → 偏好设置 → 插件` → 右上角 `从磁盘安装…`；
2. 选 `studio/blender_addon/dist/gcstudio-0.1.0.zip`；
3. 在列表里勾选 **Garment Studio**（分类栏在 3D 视图右侧，标签 `GC Studio`）。

面板从上到下：仓库（自动探测 `ChatGarment-main`，绿勾=可用）、设计 JSON、输出目录、帧数/质量，
然后四个按钮：**1. 生成纸样**（≈10–16 s）、**2. 布料仿真**（≈1–2 min）、**3. 载入结果**（导入 `sim.glb`，
对象名会加 `GC_` 前缀）、**打开输出文件夹**（在 Blender 自己的桌面会话里跑，所以能真的弹窗）。
底部是状态行 + 最近 8 行日志；跑的时候按钮变灰，完成后自动刷新。

为什么不在插件里点一下从图直接到 3D：纸样要 10–16 s、仿真 1–2 min，而 Blender UI 是单线程的，
在面板回调里同步跑会整窗假死。所以插件只负责"提交作业 + 看进度 + 载入结果"，计算在后台子进程里。

卸载：偏好设置里取消勾选，再删 `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\gcstudio\`；
`win/cleanup.ps1` 也会连带删除它（见下）。

## 一次完整验收（≈5 分钟）

1. 双击 `win/studio.bat` → 浏览器打开面板（8765 端口）；
2. 在聊天里说"用 <某张图> 做一件 <描述>"，或者直接 `python -m studio.agent new --image ... --title ...`；
3. 模型写好描述后，面板中间那块文本框里点 **没问题，生成 JSON**（不满意就直接改字再点"按我改的来"）；
4. 确认会被插件投回会话，模型写 `design.json` 并跑 `studio.job_runner`；
5. 面板上出现 2D 纸样 / 网格预览 / 布料仿真三视图 / `sim.glb` + `.blend` 下载；
6. 打开 Blender → 右侧 `GC Studio` 面板 → 输出目录填 `<job>/package` → **3. 载入结果**。

验收时可对照的产物（本机已跑过）：`studio/jobs/20261106-190913-验收-条纹短袖-大摆中长裙-bc68/`
（约 18 k 顶点、纸样 16 s + 仿真 79 s，三视图见 `package/sim/sim_views.png`）。

## 「打开文件夹」为什么可能没反应

面板按钮走 `POST /api/jobs/<id>/open` → 服务端调 `os.startfile()`。如果服务进程是在
**沙箱/后台会话**里起来的（没有可用的 window station），Windows 会直接拒绝：实测
`os.startfile` → `WinError 5 拒绝访问`，退一步用 `explorer.exe` → 退出码 `3221225794 (0xC0000142)`。

所以现在的行为是：

- 成功 → 顶部提示"已在资源管理器打开：<路径>"；
- 失败 → 提示具体原因，并**把路径复制到剪贴板**（粘贴到资源管理器地址栏即可）；
- 面板嵌在 DSH 侧栏里时，还会请 DSH 宿主进程代开（它跑在你的桌面会话里，能真正拉起窗口）。

想让它百分百好使：双击 `win/studio.bat` 启动面板（用你自己的桌面会话），而不是从受限终端起服务。

## 三条硬限制（v1 有意为之）

1. **只支持整件式（wholebody_garment）**。上下装拆分（`upperbody_garment`+`lowerbody_garment`）会被拒绝：
   GCrc 会生成两份纸样，v1 的管线只能承载一份，不拒绝就会静默丢掉下半身。
2. **浮点是归一化值 [0,1]**（(真值-lo)/(hi-lo)，范围见 `assets/design_params/design_used.yaml`）。
   要新增/修改参数，先改结构，再用 `studio.agent template` 拿到权威的浮点清单。
3. **有袖款式只能算"大致可用"**。袖片先排除在 x/y 压缩之外，再按手臂柱面（PCA 拟合轴线 + 分带半径表）
   卷到手臂上，弧长封顶 170° 防止自我重叠；tee+长裙 2.4 万顶点能稳定垂到脚踝。
   但半径偏大时袖口会蓬、褶子偏碎，袖窿环仍不钉（钉上会自我折叠并炸）。要更准需按袖窿弧长解半径。

## 失败时发生什么

| 情况 | 行为 |
|---|---|
| design.json 不合法 / 拆分款 | 退出码 2，报 `design` 错误，提示怎么改 |
| GCrc 拒纸样（缝合/裁片不自洽） | 退出码 3，报 `pattern` 错误，提示微调相邻浮点 ±0.05 |
| 布料炸开（bbox 任一分量 > 5 m） | 退出码 4，`exploded=true`，面板不会展示烂网格 |
| 仿真超过 1200 s | 退出码 4，提示降 quality / 减裁片 |
| 重网格（> 15000 顶点） | 自动降档 frames ≤ 72、quality ≤ 6 |

## 可删性

整个 `studio/` 目录（含 `jobs/`、`runs/`）可以整体删除；DSH 插件在 `studio/dsh-plugin/`，
执行 `install.ps1 -Uninstall` 会删掉 `~/.dsh/profiles/web/node_modules/dsh-garment-studio` 与
`cordis.patch.yml` 里那一条 insert。没有注册表、没有全局包、没有 PATH 改动。

- 设计文档：`../docs/STUDIO_SPEC.md`
- 模型操作手册：`../docs/GC_STUDIO_SKILL.md`
