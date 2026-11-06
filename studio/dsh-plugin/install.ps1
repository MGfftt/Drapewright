# Garment Studio 的 DSH 插件安装器（离线，不需要 pnpm / 不需要联网）
#
# 做的事：
#   1. 把 studio/dsh-plugin/ 拷进 %USERPROFILE%\.dsh\profiles\web\node_modules\dsh-garment-studio\
#   2. 在 profiles\web\cordis.patch.yml 追加一条 { id: garment-studio, name: dsh-garment-studio }
#   3. 打印重启提示
#
# 可重复执行；-Uninstall 卸载（删目录 + 删 patch 条目 + 备份 patch 层）。
# 插件本体只做两件事：侧栏 iframe 面板 + 把「人已确认」投回会话；
# 真正的界面/构建/仿真都在仓库里的 studio/ 下，删掉这个插件不影响它们。

param(
    [string]$DshHome = $(if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:USERPROFILE ".dsh" }),
    [string]$Profile = "web",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$profileDir = Join-Path $DshHome "profiles\$Profile"
$patchFile = Join-Path $profileDir "cordis.patch.yml"
$dest = Join-Path $profileDir "node_modules\dsh-garment-studio"
$marker = "id: garment-studio"

if (-not (Test-Path $profileDir)) {
    throw "找不到 profile 目录：$profileDir（确认 DSH_HOME 与 Profile 是否正确）"
}

if ($Uninstall) {
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    if (Test-Path $patchFile) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        Copy-Item -Path $patchFile -Destination "$patchFile.bak-$stamp" -Force
        $lines = Get-Content -Encoding UTF8 $patchFile
        $kept = New-Object System.Collections.Generic.List[string]
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match "^\s*-\s*$marker") {
                if ($kept.Count -gt 0 -and $kept[$kept.Count - 1].Trim() -eq "- insert:") {
                    $kept.RemoveAt($kept.Count - 1)
                }
                $i++
                if ($i -lt $lines.Count -and $lines[$i] -match "^\s*name:") { $i++ }
                while ($i -lt $lines.Count -and $lines[$i] -match "^\s{4,}\S") { $i++ }
                $i--
                continue
            }
            if ($lines[$i] -match "^#\s*Garment Studio") { continue }
            $kept.Add($lines[$i])
        }
        [System.IO.File]::WriteAllLines($patchFile, $kept, (New-Object System.Text.UTF8Encoding($false)))
    }
    Write-Host "已卸载 garment-studio（重启 DSH 后侧栏图标消失）。"
    exit 0
}

New-Item -ItemType Directory -Force -Path (Join-Path $dest "lib") | Out-Null
Copy-Item -Path (Join-Path $src "index.js") -Destination $dest -Force

# 插件被拷进 node_modules 后，index.js 已经推算不出仓库根（HERE 不再是 studio/dsh-plugin），
# 所以安装时把仓库绝对路径钉在 repo.txt 里；仓库整体搬走时重跑一次安装即可。
$repoRoot = Split-Path -Parent (Split-Path -Parent $src)
[System.IO.File]::WriteAllText((Join-Path $dest "repo.txt"), $repoRoot, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "仓库根已钉在 repo.txt：$repoRoot"
Copy-Item -Path (Join-Path $src "package.json") -Destination $dest -Force
Copy-Item -Path (Join-Path $src "lib\client.js") -Destination (Join-Path $dest "lib") -Force
if (Test-Path (Join-Path $src "README.md")) {
    Copy-Item -Path (Join-Path $src "README.md") -Destination $dest -Force
}
Write-Host "插件文件已就位：$dest"

if (-not (Test-Path $patchFile)) {
    New-Item -ItemType File -Force -Path $patchFile | Out-Null
} else {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Copy-Item -Path $patchFile -Destination "$patchFile.bak-$stamp" -Force
    Write-Host "已备份 patch 层：$patchFile.bak-$stamp"
}

$text = Get-Content -Raw -Encoding UTF8 $patchFile
if ($text -and $text.Contains($marker)) {
    Write-Host "patch 层里已登记 garment-studio，跳过追加。"
} else {
    $eol = [Environment]::NewLine
    $block = @(
        "",
        "# Garment Studio：侧栏面板 + 把人工确认投回会话（见 studio/dsh-plugin/README.md）",
        "- insert:",
        "    - id: garment-studio",
        "      name: dsh-garment-studio"
    ) -join $eol
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if (-not $text.EndsWith("`n")) { [System.IO.File]::AppendAllText($patchFile, $eol, $utf8) }
    [System.IO.File]::AppendAllText($patchFile, ($block + $eol), $utf8)
    Write-Host "已登记到 patch 层：$patchFile"
}

Write-Host ""
Write-Host "下一步："
Write-Host "  1) 重启 DSH（关掉 dsh web 窗口再启动），侧栏会出现「Garment Studio」图标"
Write-Host "  2) 面板服务没起来时插件会自己拉起来；也可以手动起："
Write-Host "     cd <repo>; .\.venv\Scripts\python.exe -m studio.server --port 8765"
Write-Host "  3) 不装插件也能用：浏览器直接开 http://127.0.0.1:8765/"
