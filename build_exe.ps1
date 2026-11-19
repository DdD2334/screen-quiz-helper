# ============================================================
#  构建脚本：把 screen-quiz-helper 打成 Windows 单文件 exe
#  前置：pip install pyinstaller
#  用法：powershell -ExecutionPolicy Bypass -File build_exe.ps1
#  说明：config.json 不打进 exe（T7 app_dir() 处理 frozen 路径，
#        exe 首次运行会在 exe 旁边自动生成/读取 config.json）。
#        --windowed 下 stdout 不可见，排障看 exe 旁 logs\app.log。
# ============================================================

$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
Set-Location $projectDir

Write-Host "[build] project: $projectDir" -ForegroundColor Cyan

# 1) 清理（保留 pack.spec）
Remove-Item -Recurse -Force .\build, .\dist -ErrorAction SilentlyContinue

# 2) 打主程序（用 pack.spec 精简：只带运行必需的 Qt 组件与中文翻译）
Write-Host "[build] packaging main.py -> dist\screen-quiz-helper.exe ..." -ForegroundColor Yellow
python -m PyInstaller --noconfirm --distpath .\dist --workpath .\build pack.spec

if ($LASTEXITCODE -ne 0) {
    Write-Host "[build] PyInstaller failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

# 3) 复制 config.json 到 dist（exe 首启也会自动生成，这里给一份现成的）
if (Test-Path .\config.json) {
    Copy-Item .\config.json .\dist\config.json -Force
    Write-Host "[build] copied config.json -> dist\" -ForegroundColor Green
}

# 4) 生成 start-exe.bat
$bat = @"
@echo off
setlocal
cd /d "%~dp0"
start "" ".\screen-quiz-helper.exe"
endlocal
"@
$bat | Out-File -Encoding ASCII .\dist\start-exe.bat
Write-Host "[build] generated dist\start-exe.bat" -ForegroundColor Green

Write-Host ""
Write-Host "=== BUILD DONE ===" -ForegroundColor Green
Write-Host "  exe:  $projectDir\dist\screen-quiz-helper.exe"
Write-Host "  bat:  $projectDir\dist\start-exe.bat"
Write-Host "  cfg:  $projectDir\dist\config.json"
Write-Host ""
Write-Host "验收提示：" -ForegroundColor Cyan
Write-Host "  1. 把 dist 拷到任意干净文件夹，双击 exe 应能启动"
Write-Host "  2. 首次运行会在 exe 旁自动生成 config.json 并弹设置向导"
Write-Host "  3. 出问题看 exe 旁 logs\app.log（--windowed 无控制台输出）"