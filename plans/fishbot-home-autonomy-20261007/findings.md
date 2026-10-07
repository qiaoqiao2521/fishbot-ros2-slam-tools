# Findings

- The existing inspection runner completes three fixed named coordinate goals and RGB classification. It does not yet provide active viewpoint selection or low-battery task interruption.
- The installed Jazzy stack exposes DockRobot and UndockRobot actions. Existing docking configuration disables battery feedback; the new fixture must enable and validate it.
- The latest partial map is a 5 cm occupancy grid. Its original bytes, origin and known observations must remain traceable after synthetic completion.

## Integrated diagnostics

- Trials 01 and 02 stopped on replanning failure. Trial 02 retained both costmaps and scan/TF inputs.
- Trial 02 global map added 140 lethal cells in static-map free space. A six-cell cluster alone sealed the narrow connection after identical footprint inflation.
- Current scan projection explains five of those cells. AMCL yaw differed from truth by 5.44 degrees; at about two meters, that shifts wall returns substantially.
- Clearing the global map did not cure the repeatable projection error. This fully mapped static fixture now uses global static/inflation layers. Live local lidar and Collision Monitor remain enabled.
- Trial 03 canceled its active navigation on low battery and reached the docking staging pose. Dock approach then failed local collision checks. Charging was not accepted; final stop was verified.
- Cleanup now cancels the action and verifies stationary feedback before synchronous diagnostic file I/O. A regression test checks that order.
- The installed Nav2 release is 1.3.13. Docking uses the stock SimpleChargingDock plugin and independent current/contact/SOC acceptance in the mission runner.

References: [Nav2 docking tutorial](https://docs.nav2.org/jazzy/tutorials/general_tutorials/using_docking/), [Jazzy docking controller source](https://github.com/ros-navigation/navigation2/blob/1.3.13/nav2_docking/opennav_docking/src/controller.cpp). The controller checks projected footprints in its fixed frame; success from the stock action is insufficient to establish fresh sustained charging.

## Narrow passage and controller selection

- Trials 04 and 07 verified simulated charging and undocking, then stopped at the narrow turn with RPP.
- Native footprint replay of trial 04 isolated local rasterization error. A 1 cm local grid removed those recorded collisions across four grid phases.
- Trial 07 still stopped. Its AMCL position differed from physical truth by about 7.1 cm.
- Geometry analysis found a 0.320 m gap between measured wall corners. The model fits, but the centered padded footprint has only about 2.5–3.4 cm clearance.
- This gap is a property of the extruded occupancy map, not a measurement of the real doorway. Inflation tuning cannot create room for a 7 cm localization error.
- Trial 10 used MPPI for every goal. Median physical speed was 0.013 m/s, and docking staging exceeded its 120 s deadline.
- The home tree now tries RPP first. A completed controller error 104, 105 or 106 permits MPPI for the remaining goal. TF, path and stale-costmap errors do not trigger that fallback.
- Trial 11 crossed the previous corner under this tree but remained slow. It was intentionally canceled, and the independent report check verified stationary termination.
- A simplified acceleration-limited MPPI sampling experiment reproduced the low forward speed at temperature 0.3. The accepted configuration uses 0.1; collision penalties and limits remain unchanged.
- Trial 12 completed camera inspection, active re-observation and verified charging/resumption, but final home navigation failed the progress check.
- Near the home goal, path-angle guidance stopped inside 0.4 m. Rotation Shim only controlled terminal yaw inside the 0.05 m positional tolerance.
- The final heading-to-goal error exceeded the maximum rotation available within the MPPI horizon. Trial 13 retains path-angle guidance until 0.05 m.
- Native replay of trial 12's final local grid found no lethal footprint collisions across full rotation, target approach and terminal rotation. Continuous simulated wall geometry also left clearance. This supports the steering diagnosis without proving earlier RPP predictions were false.
- Map loading now matches Nav2 1.3.13 float32 probabilities and inclusive threshold comparisons. Assumed pixels use 0/255 to preserve free/occupied classification at extreme thresholds.
- For this source map, the threshold fix preserves all known pixels, all occupancy classifications, scene XML and semantic goals. Only assumed free pixel encoding and file hashes change.

## Accepted result

Trial 13 passed all seven checks after the terminal steering correction. Its report SHA-256 is `8e49b0560a0a97bc51b1039710a0863904730a45438179d6435c307074ff272c`. This is one complete scenario acceptance, not a multi-scene reliability statistic.

Disabled charging and a short action deadline both produced verified stationary failures. The disabled-charge verifier must receive the test's explicit low-SOC override of 0.35; the scene model's default remains 0.28. No runtime report was rewritten to change its outcome.
