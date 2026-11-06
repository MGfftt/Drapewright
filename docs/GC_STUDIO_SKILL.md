# GC Studio 操作手册（给模型的执行步骤）

> 触发：用户说"用这张图做一件衣服 / 走 GC Studio 流程 / 生成纸样"，或者在 Garment Studio 面板里确认了一段描述。
> 全程只做一件事：把"人的一句话 + 一张图"变成 `studio/jobs/<id>/package/`（纸样 + 3D 包 + 布料仿真三视图 + sim.glb）。
> 工作目录固定为 `ChatGarment-main`，所有命令都用 `./.venv/Scripts/python.exe`。
> 规范见 `docs/STUDIO_SPEC.md`。

## 0. 三条硬规则

1. **只做整件式（wholebody）**。`wholebody_garment` 里同时给 `meta.upper` 和 `meta.bottom`（例如 `{"upper":"FittedShirt","wb":null,"bottom":"Skirt2"}`）。
   `upperbody_garment` + `lowerbody_garment` 的上下装拆分会被 **明确拒绝**——GarmentCodeRC 会出两份纸样，v1 只能承载一份，不拒绝就会静默丢掉下半身。
2. **浮点全部 [0,1]，且都是"归一化值"**：GCrc 的每个参数在 `assets/design_params/design_used.yaml` 里有 `range`，浮点 = (真值-lo)/(hi-lo)。
   默认取中段偏保守 0.35–0.65，只有描述明确要求时才走极端（<0.15 或 >0.85），相邻两个参数不要同时贴极值。
3. **不猜数字**：每个浮点都要能从描述逐条对应到参数。描述没提的用 0.5；描述提到"同款但更长"就只动 length。
4. **袖子能跑，但只能算"大致对"**：袖片会按手臂柱面卷上去（弧长封顶 170°），不会再塌、不会炸，但袖口偏蓬、褶子偏碎。
   描述里有袖就照常做，只需要在交付时说一句「袖形是近似，袖窿/袖口细节不精确」。
   注意：有袖的网格动辄 2 万顶点以上，job_runner 会自动降到 72 帧 / quality 6，一次仿真约 130 s。

## 1. 建 job、缓存图片

用户在聊天里拖入的图片，本地副本路径会出现在附件说明里（形如 `C:\Users\41239\.dsh\attachments\v1\objects\xx\<sha256>`）。
先转成真正的图片文件（扩展名要和字节一致，否则面板显示不出来），再建 job：

    ./.venv/Scripts/python.exe -m studio.agent new \
        --image <图片路径> --title "抹胸短裙" [--session <DSH sessionId>] [--notes "用户原话"]

输出 `{"job_id": "...", "stage": "created"}`。job 目录里会有 `input.png` 与 `request.json`。

## 2. 看图写描述（人类可读、按部件分段）

> 描述只写**结构**：款式、领型、袖长、腰线、裙长、松量、长度比例。不要写颜色、面料、印花、拉链、口袋、纽扣——
> GCrc 的表示里没有这些，写了模型也只能映射成别的形状，反而误导。

    ./.venv/Scripts/python.exe -m studio.agent describe <job_id> --file desc.txt

写成 5 段左右，便于人逐条核对：**整体 / 衣身 / 领与袖 / 下装 / 长度与松量**。
只写"看得见、能被参数化"的东西：款式类型、领型、袖长、衣长、松量、腰线位置、裙型、裙长、褶量、开衩。
**不要写材质、颜色、印花、拉链、口袋、纽扣**——GCrc 表达不了，写进去会在第 4 步变成错误参数。
不确定的地方写"（不确定：…）"，让人在面板里改。

写完**结束这一轮**，告诉用户："描述已生成，请在 Garment Studio 面板确认或修改"。不要自己往下写 design.json。

## 3. 等审批

面板会写 `approval.json`，DSH 插件随后投一条消息回来。也可以主动等：

    ./.venv/Scripts/python.exe -m studio.agent wait <job_id> --timeout 900

- `decision="accept"` → 以 `description.txt` 为准。
- `decision="edit"` → 以 `approval.json.text` 为准（**人改过的文本优先，逐字遵循**）。
- 文本自相矛盾（"长袖"又说"无袖"）时停下来问人，不要自己调和。

## 4. 写 design.json

先拿浮点清单——**这一步不用猜键名**：

    ./.venv/Scripts/python.exe -m studio.agent template --file garment.json

`garment.json` 只要写结构（`{"wholebody_garment": {...}}`），输出会把每个浮点路径都列出来、值都是 0.5。把 0.5 换成你的估计即得到 design.json：

    {"schema": "gcstudio/design/1",
     "label": "一句话款式名",
     "garment": {"wholebody_garment": {...}},
     "floats": {"design.shirt.length": 0.42, ...}}

写进 `studio/jobs/<id>/design.json`，然后自检（不启动 Blender，10 秒级）：

    ./.venv/Scripts/python.exe -m studio.core.cli build --design studio/jobs/<id>/design.json --out <临时目录> --tag check

退出码 0 = 纸样生成成功；2 = design 文件本身错（按报错改，不算重试）；3 = GCrc 拒绝（微调相邻浮点 0.05 再试，最多 2 次，仍失败就如实告诉人）。

## 5. 生成 3D 包 + 布料仿真

    ./.venv/Scripts/python.exe -m studio.agent run <job_id> --frames 96 --quality 8

内部两步：`studio.core.cli build` → `package/`（纸样 SVG/PNG、OBJ、sidecar、manifest），然后 `blender -b --python studio/sim/cloth_setup.py` → `package/sim/`（sim.glb、正面/侧面/背面渲染、sim_views.png 三视图拼图、sim.json）。
典型耗时：纸样 10–16 s，仿真 60–200 s（顶点越多越慢）。退出码 4 = 仿真失败，读 `package/sim/sim.json` 或 job 的 `log.txt`。

## 6. 收尾

    ./.venv/Scripts/python.exe -m studio.agent show <job_id>

把 `stage=simulated` 和 `images`（pattern / preview / sim / glb / blend）告诉用户：面板里能看到 2D 纸样、网格预览、布料仿真三视图，并可下载 `sim.glb`（Blender / Windows 3D 查看器可打开，只有最终一帧）和
`sim_drape.blend`（Blender 工程：身体 + 衣服 + Cloth 修改器 + 已烘点缓存，双击就能在 Blender 里看、拖参数重算；约 15 MB）。
如果用户问「在 Blender 里怎么看」，就答：双击 `package/sim/sim_drape.blend`（或 `File → Open`），`body` 是人体、`garment` 是衣服，空格播放看缓存，选中 `garment` 在扳手面板里改 Cloth 参数后重算；只想轻量看模型就用 `File → Import → glTF 2.0` 导入 `sim.glb`。

如果用户已经装了 Blender 侧栏插件（`studio/blender_addon/dist/gcstudio-0.1.0.zip`，面板在 3D 视图右侧 `GC Studio`），就不必让他记路径：
把 `package` 目录填进「输出」框，点 **3. 载入结果** 即可；同一面板上的 **1. 生成纸样 / 2. 布料仿真** 等价于 `agent run`，
只是作业在 Blender 的子进程里跑、面板只显示进度。注意插件与 CLI 用的是同一份管线，模型侧仍按上面 6 步走，不要假设面板会自动生成 design.json。

## GCrc 可选值速查（写 garment 结构时用）

| 字段 | 合法值 |
|---|---|
| `meta.upper` | `FittedShirt`、`Shirt`、`null` |
| `meta.wb`（腰头） | `StraightWB`、`FittedWB`、`null` |
| `meta.bottom` | `SkirtCircle`、`AsymmSkirtCircle`、`GodetSkirt`、`Pants`、`Skirt2`、`SkirtManyPanels`、`PencilSkirt`、`SkirtLevels`、`null` |
| `collar.f_collar` / `b_collar` | `CircleNeckHalf`、`CurvyNeckHalf`、`VNeckHalf`、`SquareNeckHalf`、`TrapezoidNeckHalf`、`CircleArcNeckHalf`、`Bezier2NeckHalf` |
| `collar.component.style` | `Turtle`、`SimpleLapel`、`Hood2Panels`、`null` |
| `sleeve.armhole_shape` | `ArmholeSquare`、`ArmholeAngle`、`ArmholeCurve` |
| `sleeve.cuff.type` | `CuffBand`、`CuffSkirt`、`CuffBandSkirt`、`null` |
| `pants.cuff.type` | 同上 |

别的键（`shirt`、`sleeve`、`skirt`、`pencil-skirt`、`waistband`、`pants`…）里放 `null` 占位即可；
少写一个块就少一组浮点，**结构决定浮点清单**，所以先定结构再 `template`。

两条关于裙型的实测经验（2026-11 验证）：

- `SkirtLevels`（蛋糕裙）结构上真有分层荷叶边，但**做不了迷你长度**：base 裙 + 每层固定 10 cm 荷叶，最短配置垂坠后仍到脚踝/小腿。要"迷你 + 荷叶边"用 `Skirt2` 或 `SkirtCircle` 把 `ruffle` 给到 0.9–1.0 做高抽褶近似，交付时说明"三层接缝丢弃、只保留抽褶外展"。
- `PencilSkirt` / `Skirt2` 的 `length` 很小（≤0.15）才是大腿中段；给到 0.5 就是及膝，**先 `build` 看 bbox 再 `run`**，纸样 12 s 比仿真 4 分钟便宜。

## 反模式（不要做）

- ❌ 不写描述就直接给 JSON（人没有可审的东西，等于黑箱）。
- ❌ 把人改过的描述"意译"回自己的版本（人改的字就是需求）。
- ❌ 编造浮点键名或自己发明参数（GCrc 只有 design_used.yaml 里那些）。
- ❌ 手写 `upperbody_garment`+`lowerbody_garment`（v1 直接拒绝，见第 0 节）。
- ❌ 用官方数字投影层猜数字（4-bit 下会静默贴边界值，产出"合法但荒谬"的衣服；见 docs/STUDIO_SPEC.md 的说明）。
- ❌ 往 `repos/`、`.venv/` 里写东西（第三方与依赖：可删，不要改）。
