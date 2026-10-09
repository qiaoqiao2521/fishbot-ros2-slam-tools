# Main-board clock repair

## Runtime policy

The UDP motion firmware periodically synchronizes its native micro-ROS epoch.
It attempts synchronization every five seconds with a 50 ms receive budget.
Only successful synchronization renews the 15-second clock lease.
Waiting for an Agent uses a separate discovery ping. Connected sessions use
successful synchronization as their heartbeat. The installed Agent only replies
to TIMESTAMP for a known client and session; stateless ping can succeed after
the Agent loses the XRCE session. Lease expiry recreates the session and entities.
One missed 100 ms ping no longer tears down an otherwise leased connection.

The motor task independently checks the clock lease and the existing 500 ms
receive watchdog. Invalid clock state clears cached motion commands.
Recovery requires a new command. Sensor publication skips repeated or backwards
native epochs; it never clamps or replaces their timestamps.
The display task reads a protected epoch snapshot instead of invoking RMW on
the other core. Session teardown releases both publishers and initialization
options, including the copied-options ownership boundary in Humble.
All entity creation and executor wiring steps must succeed before entering the
connected state. A failed step stops creation and rolls back partial resources.
Cleanup skips missing context/RMW handles and releases callbacks before entities.
The existing periodic serial diagnostic includes sync duration, UDP RSSI, actual
Wi-Fi power-save mode, configured transmit-power limit, minimum free heap, and
UDP write-call statistics.

## Delayed replies

The built Micro-XRCE-DDS Client 2.4.2 accepts timestamp replies without matching
their originate time to the current request. Ordinary executor reception can
also process late replies. Therefore a short synchronization timeout alone
does not bound later clock changes.

The application-owned UDP transport accepts only a reply
matching the latest successfully transmitted request and arriving within that
request's explicit begin/end window. It also validates timestamp encoding,
session identity, server time order and round-trip bounds.
The whole datagram is validated before the pending request is consumed.
A malformed or stale reply causes its entire mixed datagram to be discarded;
other best-effort messages in that packet may therefore be lost.
SDK sources remain unchanged.
Quiet hardware acceptance is required before treating that repair as effective.

The receive profile covers the current small DATA, status, ping, ACK and heartbeat
forms whose actual SDK consumption agrees with their declared boundaries.
The receive profile also accepts the observed 28-byte Agent INFO pong, with
properties absent, Agent activity present and an empty address list.
Its final six bytes must be zero: the old Client treats the last four bytes as
a zero-length submessage rather than consuming the newer address-list field.
The first filter rejected this legitimate pong; a real UDP capture identified
the mismatch and now supplies a permanent regression fixture.
It rejects other unsupported formats, fragmented inbound messages, other INFO
configuration and REQUESTER DATA. Large messages or new XRCE features need an
explicit profile extension and tests. This is not a general XRCE firewall.

## Build and checks

Build only this firmware project with PlatformIO:

```bash
pio run -d fishbot_motion_control_microros -e fishbot_motion_control_humble
python3 -B tools/tests/test_firmware_time_sync.py
python3 -B tools/tests/test_firmware_xrce_time_filter.py
```

The checked configuration pins espressif32 6.8.1, the top-level micro-ROS and
FishBot library revisions, and public `microros-colcon.meta` resource limits.
The observed toolchain uses Arduino 2.0.17, ESP-IDF 4.4.7 and Client 2.4.2.
Transitive ROS branches and Python tooling are not a complete release lock.
The private build receipt records their actual revisions.

Identify the motion board and installed partition layout before any write.
Keep a private full backup and effective-settings readback.
The current repair writes only the installed application slot.
It does not use the legacy merged-image release path.
Never publish provisioning data, serial logs, flash images or runtime captures.

## Current hardware boundary

Application writes and image hashes have been verified on the identified board.
All 28 effective settings matched after the updates; raw NVS bytes did change
after runtime boot, and the exact cause was not attributed.
An earlier application passed three stationary receiver restarts without a board
reset. Three quiet observations lasting over 120 seconds still failed native
freshness, including the reply-filter application. Radar timestamps stayed fresh.
Raw UDP odometry was already seconds old on arrival before Agent/DDS processing.
That observation does not uniquely distinguish source-clock error from transport
delay. Captures also showed valid ping replies followed by client session deletion;
host-side reply timing does not establish the board's receive timing.
The next application removed connected ping teardown, but a repeated-restart
test recovered only its first cycle, and quiet source acceptance still failed.
The current application also fixes partial entity creation and safe rollback.
Its 41 policy/lifecycle/filter checks and PlatformIO build passed; current-board
sustained freshness and receiver-restart acceptance remain pending.

A passive physical-interface capture matched 454 odometry stamps to DDS delivery.
NIC-to-DDS delay was at most 5.14 ms. Every stale matched sample was already stale
at NIC ingress. UART-to-wire correlation independently found timestamp requests
arriving at the host after their board-side timeout had already been reported,
including a 3.20-second gap. This establishes delay before the host NIC; board
transmit queues, radio and AP delivery are not yet separated. Host VPN and routes
were not changed. The Agent's logged port 47138 is the network-byte-order integer
for actual port 8888, not evidence of a different socket or NAT.
Failed attempts remain preserved; navigation remains pending.

## Wireless diagnostics

The existing Wi-Fi setup already calls `WiFi.setSleep(WIFI_PS_NONE)`.
Arduino 2.0.17 forwards this setting to the IDF API;
see its [sleep setter and getter](https://github.com/espressif/arduino-esp32/blob/2.0.17/libraries/WiFi/src/WiFiGeneric.cpp#L1303-L1315)
and the [ESP-IDF 4.4.7 power-saving guide](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32/api-guides/wifi.html#esp32-wi-fi-power-saving-mode).
Odometry and IMU publishers already use `best_effort`.
Application 8's UART diagnostics reported `wifi_ps=0` with `wifi_ps_err=0`,
confirming the board's reported power-save mode was `WIFI_PS_NONE`.
The reported maximum transmit-power setting was 78 quarter-dBm, or 19.5 dBm.
This reports the configured limit, not measured power for each transmitted frame.

Returned UDP write calls reported interval maxima from 1.753 to 8.639 ms.
The count includes all transport writes between snapshots, including failed
writes, sensor publication and entity creation. Timing includes local packet
handling and the reply filter; it does not measure wireless delivery.
Arduino 2.0.17 uses [`sendto`](https://github.com/espressif/arduino-esp32/blob/2.0.17/libraries/WiFi/src/WiFiUdp.cpp#L166-L176)
inside `endPacket`; long write duration alone cannot identify transmit-buffer congestion.
The communication task's priority of 1 alone cannot establish task starvation;
see [IDF task-priority guidance](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32/api-guides/performance/speed.html#choosing-application-task-priorities).
Both hypotheses require timing or scheduling evidence that separates the causes.

The minimum-free-heap diagnostic fell from 110096 to 77672 bytes.
Arduino's [`getMinFreeHeap`](https://github.com/espressif/arduino-esp32/blob/2.0.17/cores/esp32/Esp.cpp#L135-L138)
reports the internal heap's historical low-water mark since boot.
That decline alone does not establish a memory leak.

Three stationary 125-second comparisons still failed native source freshness:

| Comparison | Maximum native age | Out-of-limit samples | Longest receive gap |
| --- | ---: | ---: | ---: |
| Application 8 baseline | 5.116558847 s | 435 | 18.187 s |
| Computer Wi-Fi power saving disabled | 4.317139 s | 391 | Not reported here |
| Radar receiver stopped | 3.732566 s | 475 | Not reported here |

Application 8 preserved all 28 effective settings; no motion occurred.
Computer Wi-Fi power saving was restored to its original enabled state.
The radar receiver was restored, and 20 fresh scans passed its readiness check.
Stopping only that receiver does not exclude all wireless contention.
The earlier capture's maximum NIC-to-DDS delay remains 5.14 ms; these results
still leave board queues, radio and AP delivery unresolved.

A lower-publication-load comparison changed `odom_pub_period` from 50 to 200 ms;
post-startup requested readback confirmed that setting and the other 27 values.
The 125.98-second observation still failed: maximum native age was 0.612 seconds,
with three violations. Only 57.91 seconds of odometry were delivered, followed
by a terminal 67.10-second receive gap; the smaller age maximum is not acceptance.
The original 50 ms period and all 28 effective settings were restored and read back.
Sustained physical freshness and repeated reconnection remain pending. The user
ended further wireless experiments. Subsequent fixed-map outbound and resumed
return completed with fresh stopping feedback. Short patrol remained incomplete;
matched host smoother-tail commands exceeded the independent 250 ms source gate
while native odometry was fresh. See the current progress for continuous-route
acceptance; successful short goals do not repair the earlier delivery failure.

Periodic synchronization and command-cache invalidation do not provide source
timestamp or sequence rejection for the plain `Twist` board interface.
A queued old command that is newly received still needs a separate protocol fix.
Installed-board loss-of-command stopping also requires physical acceptance.
See [current progress](../plans/fishbot-real-autonomy-20261005/progress.md).
