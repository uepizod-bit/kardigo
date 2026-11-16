@echo off
setlocal enableextensions
chcp 65001 >nul
title KADRGO Studio - o'rnatish
cd /d "%~dp0"
echo ======================================================
echo   KADRGO Studio o'rnatish (Windows 10/11 x64)
echo ======================================================

rem --- 1) Python 3.10+
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo Python topilmadi. winget orqali o'rnatilmoqda...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python o'rnatildi. Bu oynani yoping va install_windows.bat ni QAYTA ishga tushiring.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
  echo Python 3.10 yoki yangiroq kerak. https://www.python.org/downloads/ dan o'rnating.
  pause
  exit /b 1
)

rem --- 2) FFmpeg (bin\ papkasiga portativ nusxa; PATH ga tegmaydi)
if not exist bin mkdir bin
if exist bin\ffmpeg.exe goto ffok
where ffmpeg >nul 2>&1
if not errorlevel 1 goto ffok
echo FFmpeg yuklanmoqda (taxminan 100 MB)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $u='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'; Invoke-WebRequest $u -OutFile ffmpeg_dl.zip; Expand-Archive ffmpeg_dl.zip -DestinationPath ff_tmp -Force; Copy-Item (Get-ChildItem ff_tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName bin\ffmpeg.exe; Copy-Item (Get-ChildItem ff_tmp -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName bin\ffprobe.exe; Remove-Item ff_tmp,ffmpeg_dl.zip -Recurse -Force"
if not exist bin\ffmpeg.exe (
  echo FFmpeg avtomatik yuklanmadi. Qo'lda: winget install Gyan.FFmpeg  yoki  https://www.gyan.dev/ffmpeg/builds/
  echo ffmpeg.exe va ffprobe.exe ni shu papkadagi bin\ ga tashlang.
  pause
  exit /b 1
)
:ffok

rem --- 3) virtual muhit va kutubxonalar
if not exist .venv (
  echo Virtual muhit yaratilmoqda...
  %PY% -m venv .venv
  if errorlevel 1 ( echo venv yaratilmadi & pause & exit /b 1 )
)
echo Kutubxonalar o'rnatilmoqda (PySide6 ~ 150 MB, internet kerak)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ( echo O'rnatish xatosi. Internetni tekshiring. & pause & exit /b 1 )

rem --- 4) yorliq (Desktop)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\KADRGO Studio.lnk'); $s.TargetPath='%CD%\.venv\Scripts\pythonw.exe'; $s.Arguments='-m kadrgo'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\assets\kadrgo.ico'; $s.Save()"

rem --- 5) haqiqiy tekshiruv
echo.
echo O'z-o'zini tekshirish (haqiqiy render va undo sinovi)...
".venv\Scripts\python.exe" -m kadrgo info
".venv\Scripts\python.exe" -m kadrgo selfcheck
echo.
echo ======================================================
echo  TAYYOR. Desktop dagi "KADRGO Studio" yorlig'ini bosing
echo  yoki run_kadrgo.bat ni ishga tushiring.
echo  Kutubxona papkasi (SFX, shrift, LUT, plagin) uchun README_UZ.md ni o'qing.
echo ======================================================
pause
