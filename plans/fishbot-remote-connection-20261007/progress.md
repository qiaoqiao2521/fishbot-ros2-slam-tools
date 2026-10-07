# Progress

## Current
Complete. The canonical development directory owns its Git root and tracks `origin/main`. Normal push and independent GitHub API readback confirmed integration commit `3fd5bf4`.

## Done
Verified the GitHub account and target repository. Reconciled the published tree with current source and preserved independent histories.

Validation passed: 146 tool tests, 31 MuJoCo tests, 21 frontend tests, 8 legacy simulator tests, 4 layout tests, frontend build, MuJoCo build and 12 offline layout checks.

The ROS-free replay test now checks imports in a fresh process. This removes test-order interference without changing runtime behavior.

Public documents use placeholders for local provisioning. The old network guide contained a Wi-Fi password in already published history. The current file is redacted; history remains intact. The owner should rotate that password.

## Remaining
No repository-connection work remains. Hardware acceptance remains a separate task.

One preexisting nested change remains local: `fishbot_motion_control_microros/release.sh`. It adds required release inputs and the `boot_app0.bin` merge segment. Shell syntax passed, but no pinned-toolchain build or release was run. The integrated root does not publish its upstream release-workflow dependencies. Root Codex owns follow-up: review the nested diff, bind the matching toolchain artifact and validate an isolated firmware build before committing that release workflow. The file and its nested Git history are preserved; no release or flashing was attempted.

## Issues
No hardware or new end-to-end simulation run was performed for this repository connection. Earlier simulation evidence remains local.

## Next
Use the canonical project root for future integration commits and pushes. Original operational files, hashes and the application manifest remain under ignored `.local/`. Nine nested metadata directories and 316 preexisting outer tracked changes were verified unchanged.
