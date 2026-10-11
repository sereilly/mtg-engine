@echo off
rem Runs setup.ps1 whatever the machine's PowerShell execution policy is: a
rem fresh Windows install refuses .\setup.ps1 outright, and changing the policy
rem is not this repo's decision to make. Arguments pass straight through.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
exit /b %ERRORLEVEL%
