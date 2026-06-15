# Windows 平台信息

{% if bash_path %}
- 操作系统: Windows (Git Bash)
- Shell: bash（Unix 语法，路径 `/`，命令 `ls`, `grep`, `cat`, `rm` 等均可使用）
- 路径分隔符: `/`（正斜杠）
- Python: 使用 `python` 命令
- 多命令分隔符: `&&` 或 `;`
- 环境变量: `$VAR` 或 `${VAR}`
- 注意: Git Bash 不支持 Windows 风格路径（如 `C:\Users`），使用 `/c/Users` 代替
{% else %}
- 操作系统: Windows (cmd.exe)
- Shell: cmd.exe（兼容 DOS 命令，不支持 bash/PowerShell 语法）
- 路径分隔符: `\`（反斜杠）
- Python: 使用 `python` 或 `py` 命令
- 常用命令: `dir` (ls), `cd /d` (cd), `type` (cat), `del` (rm)
- 多命令分隔符: `&&`（cmd.exe 支持）
- 环境变量: `%VAR%`
- 注意: 不要使用 `ls`, `grep`, `cat`, `rm` 等 Unix 命令
- 注意: 不要使用 `Get-ChildItem` 等 PowerShell 命令
{% endif %}
