# Nav2 state confirmation patch

`nav2-1.3.13-state-query.patch` changes only lifecycle state confirmation.
The mutating transition runs once. A `std::runtime_error` from `GetState`
allows one further query while the ROS context remains active.
Each query retains the upstream two-second timeout. A returned wrong state
fails immediately. A second exception propagates to the original abort path.
The manager logs each query attempt and its steady-clock elapsed time.

Upstream source: [Nav2 1.3.13](https://github.com/ros-navigation/navigation2/tree/1.3.13).
The tag resolves to commit `f4108e5b1c2bce804a1aa0c7be6673a8eb4a1501`.
The immutable commit archive has SHA256
`dcc59eef3c0be52194707b827917212b8d6eeca8003e09b92f21343a48f9bdcb`.
The original `lifecycle_manager.cpp` has SHA256
`7d56021ac5c47315eda2a5a1003ecbcbb63355364696835d4300084de8b00f81`.
Its original Apache-2.0 copyright header remains unchanged.
`LICENSE.navigation2` preserves the repository's upstream license notice.

Build the selected package with installed Jazzy dependencies:

```bash
./tools/fishbot_nav2_state_query_overlay.sh build
./tools/fishbot_nav2_state_query_overlay.sh check
./tools/fishbot_nav2_state_query_overlay.sh prefix
```

Source, build products and receipts stay in
`${XDG_CACHE_HOME:-$HOME/.cache}/fishbot/nav2-state-query-overlay`.
`FISHBOT_NAV2_STATE_QUERY_OVERLAY_ROOT` can choose another local cache.
The workspace identity includes the commit and patch hash.
The build selects only `nav2_lifecycle_manager`, uses one compiler job,
and does not install or replace system packages.
`prefix` rejects missing, changed or untested build products.
The caller can source the returned prefix's `local_setup.bash`.
The script does not start any ROS node.

Run deterministic behavior tests against the actual patched C++ method:

```bash
./tools/fishbot_nav2_state_query_overlay.sh test
```

The harness extracts the production method verbatim. Service doubles cover
correct states, query exceptions, wrong states, mutation failures and shutdown.
These tests establish bounded control flow. They do not establish DDS recovery.

For real ROS acceptance, use an isolated service fixture and the actual manager.
Serve `ChangeState` and `GetState` under the same fixture node name.
Count every transition request and record every query arrival.
After a successful configure transition, delay only its first `GetState`
response by 2.3 seconds. Use a reentrant callback group and multiple executor
threads so the next query can return the current state immediately.
Disable bonds for this service-only fixture with `bond_timeout: 0.0`.
The unpatched manager must abort after exactly one configure request.
The patched manager must reach ACTIVE with exactly one configure request
and one activate request. Neither run may repeat a transition.
Also return an explicit wrong state or delay both queries to verify failure.
This fixture tests recovery from a lost or late confirmation. It does not
identify the original DDS stall's cause or replace full navigation acceptance.

The executable fixture is `tools/tests/verify_nav2_state_query_retry.py`:

```bash
FISHBOT_MUJOCO_DOMAIN_ID=103 source tools/fishbot_mujoco_env.sh
/usr/bin/python3 tools/tests/verify_nav2_state_query_retry.py --execute --domain 103
```

It rejects occupied domains and non-local discovery. Each case uses fresh nodes
and a separate manager process group. It verifies parameters and fingerprints
the actual loaded manager library through `/proc/<pid>/maps`.
The three cases cover stock failure, patched recovery and persistent failure.
Runtime receipts and logs remain outside the repository. Domain cleanup is
checked before and after every case. No navigation action is dispatched.
