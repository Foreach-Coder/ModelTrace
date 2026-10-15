@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "EXIT_CODE=1"

pushd "%~dp0"
if errorlevel 1 goto directory_failed

if not exist "requirements.txt" goto project_files_missing
if not exist "start.py" goto project_files_missing
if exist ".venv" goto check_environment

echo [1/3] 正在查找 Python 3.11 或更新版本...
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto create_with_py
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto create_with_python
echo [错误] 未找到可用的 Python 3.11 或更新版本。
echo 请先安装 Python，并启用 Python Launcher 或勾选 Add Python to PATH，然后重试。
goto failed

:create_with_py
echo [1/3] 正在创建项目虚拟环境 .venv...
py -3 -m venv ".venv"
if errorlevel 1 goto creation_failed
goto check_environment

:create_with_python
echo [1/3] 正在创建项目虚拟环境 .venv...
python -m venv ".venv"
if errorlevel 1 goto creation_failed

:check_environment
if not exist ".venv\pyvenv.cfg" goto environment_invalid
if not exist ".venv\Scripts\python.exe" goto environment_invalid
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 11) or sys.prefix == sys.base_prefix)" >nul 2>&1
if errorlevel 1 goto environment_invalid
echo [1/3] 项目虚拟环境已就绪。
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if not errorlevel 1 goto install_dependencies
echo 正在为虚拟环境安装 pip...
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto pip_failed

:install_dependencies
echo [2/3] 正在根据 requirements.txt 安装或更新依赖...
rem Pin both the prefix and staging root so pip configuration cannot relocate .venv.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade --no-user --prefix "%CD%\.venv" --root "%CD:~0,2%/" -r "requirements.txt"
if errorlevel 1 goto dependencies_failed

echo [3/3] 正在启动 ModelTrace：http://127.0.0.1:7860/
echo 运行期间请保留此窗口，按 Ctrl+C 可以停止服务。
".venv\Scripts\python.exe" "start.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto application_failed
goto finish

:project_files_missing
echo [错误] 缺少 requirements.txt 或 start.py，请将此脚本放在完整项目的根目录。
goto failed

:creation_failed
echo [错误] 虚拟环境创建失败，请检查上方错误和目录写入权限。
echo 如果已生成不完整的 .venv，请先将它重命名备份，再重新运行本脚本。
goto failed

:environment_invalid
echo [错误] 已有 .venv 不是可用的 Python 3.11+ 虚拟环境，本脚本未覆盖它。
echo 请将 .venv 重命名备份，确认已安装 Python 3.11+，然后重试。
goto failed

:pip_failed
echo [错误] 无法为虚拟环境安装 pip，请检查上方错误后重试。
goto failed

:dependencies_failed
echo [错误] requirements.txt 依赖安装或更新失败，应用未启动。
echo 请检查上方错误、网络连接及 Python 版本后重试。
goto failed

:application_failed
echo [错误] ModelTrace 已退出，退出码：%EXIT_CODE%。请查看上方错误信息。

:failed
echo.
pause

:finish
popd
endlocal & exit /b %EXIT_CODE%

:directory_failed
echo [错误] 无法进入项目目录。
pause
endlocal & exit /b 1
