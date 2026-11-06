@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
rem ---------------------------------------------------------------------------
rem  由你自己的桌面会话启动 Garment Studio 面板。
rem  为什么需要它：如果面板服务是被沙箱 shell / DSH 后台拉起的，进程没有可用的
rem  window station，面板里的「打开文件夹」会被系统拒绝（os.startfile -> WinError 5），
rem  这个窗口也会继承那个限制。双击本文件启动，就没有这个限制。
rem  关掉面板 = 关掉这个黑窗口（或任务管理器结束 python.exe）。
rem ---------------------------------------------------------------------------

rem 先清掉占用 8765 的旧进程（旧进程多半是受限会话里起来的）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "127.0.0.1:8765" ^| findstr LISTENING') do (
  echo 结束旧面板进程 PID %%p
  taskkill /f /pid %%p >nul 2>&1
)

if not exist ".venv\Scripts\python.exe" (
  echo 找不到 .venv\Scripts\python.exe，请在仓库根目录先建虚拟环境。
  pause
  exit /b 1
)

echo 启动 Garment Studio 面板 http://127.0.0.1:8765/ ...
start "" ".venv\Scripts\python.exe" -m studio.server --port 8765 --open
timeout /t 3 >nul
endlocal