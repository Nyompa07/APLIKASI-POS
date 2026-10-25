@echo off
setlocal
cd /d "%~dp0"
title Nilla Daily Mart - Menu Peluncur
if not exist "runtime\python.exe" goto missing
"runtime\python.exe" "%~dp0launch.py"
if errorlevel 1 goto failed
exit /b 0
:missing
echo Paket portable belum lengkap atau ZIP belum diekstrak.
echo Klik kanan ZIP - Extract All terlebih dahulu.
echo Pastikan folder runtime berada di sebelah MULAI-NILLA.bat.
pause
exit /b 1
:failed
echo.
echo Aplikasi belum berhasil dimulai. Pesan kesalahan ada di atas.
echo Jika tersedia, kirim juga berkas data\launcher.log untuk bantuan.
pause
exit /b 1
