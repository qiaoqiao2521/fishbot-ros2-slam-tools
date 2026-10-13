"""Open one native RViz per simulation domain through the existing user manager."""
import os
import subprocess
import threading
from pathlib import Path

from ament_index_python.packages import (PackageNotFoundError, get_package_prefix,
                                        get_package_share_directory)


class RvizDesktopError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class RvizDesktop:
    def __init__(self, domain):
        if type(domain) is not int or not 1 <= domain <= 232:
            raise ValueError('RViz requires an isolated simulation domain 1..232')
        self.domain = domain
        self.unit = f'fishbot-rviz-domain-{domain}.service'
        self.lock = threading.Lock()
        self.manager_env = dict(os.environ)
        runtime = self.manager_env.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        self.manager_env.setdefault('XDG_RUNTIME_DIR', runtime)
        self.manager_env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path={runtime}/bus')
        try:
            self.executable = Path(get_package_prefix('rviz2')) / 'lib/rviz2/rviz2'
            self.config = Path(get_package_share_directory('fishbot_mujoco')) / 'config/simulation.rviz'
        except PackageNotFoundError:
            self.executable = None
            self.config = None

    def run(self, command):
        return subprocess.run(command, env=self.manager_env, capture_output=True,
                              text=True, timeout=2, check=False)

    def status(self):
        result = {'available': False, 'running': False, 'domain': self.domain,
                  'message': '当前环境不能打开本机 RViz。'}
        try:
            desktop = self.run(['systemctl', '--user', 'show-environment'])
            if desktop.returncode != 0:
                result['message'] = '本机桌面会话不可用。'
                return result
            display = dict(line.split('=', 1) for line in desktop.stdout.splitlines()
                           if line.startswith(('DISPLAY=', 'WAYLAND_DISPLAY=')))
            if not any(display.values()):
                result['message'] = '控制站电脑没有可用的桌面显示。'
                return result
            if (self.executable is None or self.config is None
                    or not self.executable.is_file() or not self.config.is_file()):
                result['message'] = '本机 RViz 或 FishBot 视图配置尚未安装。'
                return result
            result['available'] = True
            unit = self.run(['systemctl', '--user', 'show', self.unit,
                             '--property=ActiveState,MainPID'])
            properties = dict(line.split('=', 1) for line in unit.stdout.splitlines() if '=' in line)
            pid = int(properties.get('MainPID', '0'))
            result['running'] = (unit.returncode == 0 and pid > 0
                                 and properties.get('ActiveState') in {'active', 'activating'})
            if result['running']:
                result['pid'] = pid
                result['message'] = f'RViz 已在控制站电脑打开（ROS 域 {self.domain}）。'
            else:
                result['message'] = f'在控制站电脑打开 RViz（ROS 域 {self.domain}）。'
        except (OSError, ValueError, subprocess.TimeoutExpired):
            result['available'] = False
            result['message'] = '本机桌面状态查询失败，请稍后再试。'
        return result

    def open(self):
        with self.lock:
            current = self.status()
            if not current['available']:
                raise RvizDesktopError(current['message'])
            if current['running']:
                return 200, current
            # Fixed executable/config and server-owned domain; never accept a
            # command, path, ROS domain or shell argument from the browser.
            command = ['systemd-run', '--user', '--collect', f'--unit={self.unit}',
                       f'--description=FishBot RViz ROS domain {self.domain}',
                       '--property=TimeoutStopSec=5']
            inherited = ('PATH', 'LD_LIBRARY_PATH', 'AMENT_PREFIX_PATH', 'PYTHONPATH',
                         'ROS_DISTRO', 'ROS_LOG_DIR', 'RMW_IMPLEMENTATION')
            for key in inherited:
                if key in os.environ:
                    command.append(f'--setenv={key}={os.environ[key]}')
            command += [f'--setenv=ROS_DOMAIN_ID={self.domain}',
                        '--setenv=ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST',
                        '--setenv=ROS_LOCALHOST_ONLY=1', '--setenv=ROS_STATIC_PEERS=',
                        str(self.executable), '-d', str(self.config), '--ros-args',
                        '-p', 'use_sim_time:=true', '-r', f'__node:=fishbot_rviz_{self.domain}']
            try:
                started = self.run(command)
                observed = self.status()
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RvizDesktopError('RViz 启动回执未知，请读取窗口状态。', 504) from error
            if started.returncode != 0 and not observed['running']:
                raise RvizDesktopError('RViz 未能启动，请查看本机桌面服务日志。')
            if not observed['running']:
                raise RvizDesktopError('RViz 尚未确认运行，请读取窗口状态。', 504)
            return (202 if started.returncode == 0 else 200), observed
