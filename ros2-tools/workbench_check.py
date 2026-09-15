#!/usr/bin/env python3
"""Read-only static audit. Exit 1 reports blockers; never starts ROS nodes."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = (
    ("apps/fishbot-control-station", "parent", None),
    ("apps/green-board-station", "parent", None),
    ("projects/robot_base", "independent", "jazzy"),
    ("projects/so101-win7-follower-demo", "independent", None),
    ("vision/uw-yolo-code-assets", "independent", None),
    ("fishbot_nav", "independent", "jazzy"),
    ("workspaces/so101_ws", "independent", "humble"),
    ("workspaces/learning_ws", "independent", "humble"),
)


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                          text=True, timeout=15,
                          env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})


def main():
    failures = 0

    def check(ok, message):
        nonlocal failures
        failures += not ok
        print(f'{"PASS" if ok else "FAIL"} {message}')

    for rel, ownership, distro in PROJECTS:
        path = ROOT / rel
        if not path.is_dir():
            check(False, f"missing project: {rel}")
            continue
        expected = ROOT.parent if ownership == "parent" else path
        result = git(path, "rev-parse", "--show-toplevel")
        actual = Path(result.stdout.strip()) if result.returncode == 0 else None
        check(actual == expected, f"{rel}: Git owner {expected}")
        check(git(path, "rev-parse", "--verify", "HEAD").returncode == 0,
              f"{rel}: committed HEAD exists")
        if distro:
            check(Path(f"/opt/ros/{distro}/setup.bash").is_file(),
                  f"{rel}: declared/historical ROS {distro} installed")
    for rel in ("apps", "vision", "_archive"):
        check((ROOT / rel / "COLCON_IGNORE").is_file(), f"colcon boundary: {rel}")
    scripts = [ROOT.parent / "ros2env", ROOT / ".ros2_env", *sorted((ROOT / 'tools').glob('*.sh'))]
    for app in ("fishbot-control-station", "green-board-station"):
        scripts.extend((ROOT / "apps" / app / "scripts").glob("*.sh"))
    for path in scripts:
        source = path.read_text(encoding="utf-8")
        check("/home/muqiao/桌面/dev/" not in source,
              f"no retired root: {path.relative_to(ROOT.parent)}")
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, timeout=10)
        check(result.returncode == 0, f"shell syntax: {path.name}")
    for name, rel in (
        ("fishbot-control-station", "apps/fishbot-control-station"),
        ("green-board-station", "apps/green-board-station"),
        ("robot_base", "projects/robot_base"),
        ("so101_win7_follower_demo_20260521-094227", "projects/so101-win7-follower-demo"),
    ):
        link = ROOT.parent / name
        check(link.is_symlink() and link.resolve() == ROOT / rel,
              f"compatibility link: {name}")
    for path in (ROOT / "AGENTS.md", ROOT / "PROJECT.md", ROOT / "PROJECTS.md",
                 ROOT / "docs/ARCHITECTURE.md", ROOT / "docs/DECISIONS.md"):
        text = path.read_text(encoding="utf-8")
        check(not any(0x80 <= ord(c) <= 0x9f for c in text),
              f"no C1 mojibake markers: {path.name}")
    print(f"{failures} blocker(s). Static only; no build, dependency or hardware certification.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
