@echo off
setlocal
set "SSH_DIR=C:\ProgramData\ssh"
set "UV_INSTALL_DIR=C:\uv"
set "UV_PYTHON_INSTALL_DIR=C:\uv-python"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null"
if errorlevel 1 exit /b 1

copy /Y C:\OEM\admin_authorized_keys "%SSH_DIR%\administrators_authorized_keys" >nul
if errorlevel 1 exit /b 1
icacls "%SSH_DIR%\administrators_authorized_keys" /inheritance:r /grant "SYSTEM:F" "Administrators:F" >nul
if errorlevel 1 exit /b 1

(
  echo PubkeyAuthentication yes
  echo PasswordAuthentication no
  echo Match Group administrators
  echo     AuthorizedKeysFile C:/ProgramData/ssh/administrators_authorized_keys
) >> "%SSH_DIR%\sshd_config"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; New-NetFirewallRule -Name OpenSSH-Server-In-TCP -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue | Out-Null; Set-Service -Name sshd -StartupType Automatic; Start-Service sshd"
if errorlevel 1 exit /b 1

if not exist "%UV_INSTALL_DIR%" mkdir "%UV_INSTALL_DIR%"
if not exist "%UV_PYTHON_INSTALL_DIR%" mkdir "%UV_PYTHON_INSTALL_DIR%"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $env:UV_INSTALL_DIR='C:\uv'; irm https://astral.sh/uv/install.ps1 | iex"
if errorlevel 1 exit /b 1

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Environment]::SetEnvironmentVariable('UV_PYTHON_INSTALL_DIR','C:\uv-python','Machine'); $p=[Environment]::GetEnvironmentVariable('Path','Machine'); if (($p -split ';') -notcontains 'C:\uv') { [Environment]::SetEnvironmentVariable('Path',($p.TrimEnd(';')+';C:\uv'),'Machine') }"
if errorlevel 1 exit /b 1

net stop sshd >nul 2>&1
net start sshd >nul
if errorlevel 1 exit /b 1
exit /b 0
