"""Stop the local editor with: python stop.py (Windows, no extra dependencies)."""
import argparse
import base64
import errno
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Check every listener before stopping any process. Never stop all Python
# processes or an unrelated application just because it occupies our port.
STOP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
    Where-Object { $_.LocalPort -eq [int]$env:RESUME_STOP_PORT -and $_.LocalAddress -eq '127.0.0.1' })
$owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
$targets = @()
foreach ($ownerId in $owners) {
    $server = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId"
    if (-not $server -or $server.CommandLine -notmatch '(?:-m\s+backend\.main(?:\s|$)|(?:-m\s+)?uvicorn(?:\.exe)?"?\s+backend\.main:app(?:\s|$))') {
        throw 'Port belongs to an unrecognized process; no process was stopped.'
    }
    $targets += $server
}
if ($env:RESUME_STOP_CHECK -ne '1') {
    foreach ($server in $targets) {
        # Recheck creation time so a recycled process ID cannot target another app.
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($server.ProcessId)"
        if ($current -and $current.CreationDate -ne $server.CreationDate) { throw 'Process changed; stop cancelled.' }
        if ($current) { Stop-Process -Id $server.ProcessId -ErrorAction Stop }
    }
}
@{ count = $targets.Count; checked = ($env:RESUME_STOP_CHECK -eq '1') } | ConvertTo-Json -Compress
"""


def main():
    parser = argparse.ArgumentParser(description='停止 Resume Rebuilder 本地编辑器服务')
    parser.add_argument('--check', action='store_true', help='仅检查服务与进程，不停止')
    parser.add_argument('--port', type=int, default=8765, help='服务端口，默认 8765')
    options = parser.parse_args()
    if not 1 <= options.port <= 65535:
        parser.error('端口必须在 1～65535 之间')
    if os.name != 'nt':
        print('此停止脚本适用于 Windows；其他系统请在启动终端按 Ctrl+C。', file=sys.stderr)
        return 1
    base = f'http://127.0.0.1:{options.port}'
    # Bypass system proxies when talking to the local service.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(base+'/api/health', timeout=3) as response:
            health = json.load(response)
        with opener.open(base+'/openapi.json', timeout=3) as response:
            schema = json.load(response)
        with opener.open(base+'/', timeout=3) as response:
            frontend = response.read()
        if (health.get('ok') is not True or health.get('localOnly') is not True
                or schema.get('info', {}).get('title') != 'Resume Rebuilder'
                or frontend != (ROOT/'frontend/dist/index.html').read_bytes()):
            raise ValueError('服务身份与当前项目不一致')
    except urllib.error.URLError as error:
        if isinstance(error.reason, OSError) and error.reason.errno in {errno.ECONNREFUSED, 10061}:
            print(f'Resume Rebuilder 未运行（端口 {options.port}），无需停止。')
            return 0
        print(f'无法确认本地服务，未停止任何进程：{error}', file=sys.stderr)
        return 1
    except (OSError, ValueError, AttributeError) as error:
        print(f'无法确认本地服务，未停止任何进程：{error}', file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment['RESUME_STOP_PORT'] = str(options.port)
    environment['RESUME_STOP_CHECK'] = '1' if options.check else '0'
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
             base64.b64encode(STOP_SCRIPT.encode('utf-16-le')).decode('ascii')],
            env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=20,
        )
        if result.returncode:
            print(f'停止检查未完成：{result.stderr.strip()}', file=sys.stderr)
            return 1
        status = json.loads(result.stdout.lstrip('\ufeff'))
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'停止检查未完成：{error}', file=sys.stderr)
        return 1
    if not status['count']:
        print('服务已退出，无需停止。')
    elif status['checked']:
        print(f'已确认 Resume Rebuilder 正在运行（端口 {options.port}）。运行 python stop.py 可停止服务。')
    else:
        print(f'已停止 Resume Rebuilder（端口 {options.port}）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
