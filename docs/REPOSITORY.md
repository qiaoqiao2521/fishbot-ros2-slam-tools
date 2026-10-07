# Repository continuity

The development checkout directly tracks [qiaoqiao2521/fishbot-ros2-slam-tools](https://github.com/qiaoqiao2521/fishbot-ros2-slam-tools), branch `main`. Fetch and push both use this existing public repository.

```bash
git rev-parse --show-toplevel
git remote -v
git status --short --branch
```

Run these commands from the FishBot project root. The Git root must be this project, rather than an outer workbench repository. Existing independent Git metadata inside upstream modules is retained; run root Git commands for the integrated project, and coordinate module-local history separately.

The October 2026 simulation, continuous passage control, radar fixes and visual inspection originally lived in an outer local repository. Their reviewed source is now integrated onto the existing remote history. The outer repository and its unrelated migration changes remain preserved. No history rewrite or force push is required.

Maps, posegraphs, firmware images/backups, machine provisioning, runtime logs, extracted dependencies and generated reports stay local. The local `.local/` directory holds original operational notes and the connection manifest. These files are ignored and must not be staged for publication. Public status is in [PROJECT.md](../PROJECT.md) and [FISHBOT_STATUS.md](../FISHBOT_STATUS.md).

The historical `_public_release` snapshot remains unchanged. It is not the development or delivery entrypoint. Hardware has not been operated by connecting this repository.
