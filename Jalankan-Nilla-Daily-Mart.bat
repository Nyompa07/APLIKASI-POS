@echo off
setlocal
cd /d "%~dp0"
title Nilla Daily Mart

where py >nul 2>nul
if %errorlevel%==0 (
  set "NILLA_PYTHON=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "NILLA_PYTHON=python"
  ) else (
    echo.
    echo Python belum terpasang.
    echo.
    echo Instal Python 3 dari https://www.python.org/downloads/
    echo Saat instalasi, centang pilihan "Add Python to PATH".
    echo Setelah itu klik dua kali berkas ini lagi.
    echo.
    pause
    exit /b 1
  )
)

start "" /B cmd /c "timeout /t 2 /nobreak >nul ^& start http://127.0.0.1:4173"

echo.
echo Nilla Daily Mart sedang berjalan.
echo Browser seharusnya terbuka secara otomatis.
echo Jangan tutup jendela ini selama aplikasi digunakan.
echo Tekan Ctrl+C untuk menghentikan aplikasi setelah selesai.
echo.
%NILLA_PYTHON% backend.py
