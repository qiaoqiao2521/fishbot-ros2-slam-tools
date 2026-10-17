# SO101 recording review browser acceptance

This project-local script reuses Lichtblick's installed Playwright library and the system Chrome executable. It creates an isolated headless browser context. It never uses the daily browser or an existing signed-in profile.

Start the approved read-only preview separately. The default endpoint is `http://127.0.0.1:5186`; it must serve `/records/so101.mcap`, `/layouts/so101-review.json`, and `/layouts/so101-mobile.json`. Full and mobile modes enter through the actual `/so101` and `/so101-mobile` shortcuts and verify their remote-file/layout/time redirect. Baseline uses the original remote-file deep link without a custom layout.

```sh
node apps/fishbot-control-station/workbench-review-tests/run-review.cjs
```

Use `--url`, `--output`, `--chrome`, or `--timeout-ms` to override the defaults. `--baseline` loads the original default layout and accepts only actual remote-record loading and native playback. It does not import the custom layout or accept custom panels, stage seek, or layout persistence. Full mode checks every configured Plot separately. The runner accepts only loopback HTTP previews. It does not start servers, install dependencies, alter source layouts, or write robot configuration.

`--mobile` loads `/layouts/so101-mobile.json` in a 390 × 844 touch viewport. It checks the actual CSS layout viewport as well, rejecting desktop pages merely scaled down by the mobile browser. The layout uses native Image and EpisodeReview panels. The test measures real geometry and horizontal overflow, reads the final report, operates native playback, scrolls to and taps a recorded stage, and confirms the camera remains drawn. Mobile does not repeat desktop layout editing, accept 3D/Plot rendering, or accept an untested mobile scene editor.

## What is accepted

- The actual record is fetched through the native remote-file data source.
- Configured Image, 3D, Plot, and EpisodeReview panels render. Raster statistics and screenshots document visible output; they do not prove geometric accuracy.
- Native stage buttons seek forward and backward. Physical time, episode stage, image, and scene respond to the recording.
- The recorded green object remains visible and clear of the 3D canvas edges at start, held-object, and settled stages. Screenshots still require human review; pixel bounds do not prove metric geometry or complete robot modeling.
- Native play, pause, and seek controls operate the record.
- A user splits EpisodeReview, saves the layout, and reloads without `layoutUrl`. The duplicate survives. Removing and saving that duplicate also survives refresh. Original data panels remain configured.
- Page load, seek, panel operations, layout persistence, and refresh make no write request or live WebSocket connection. All external requests and non-GET/HEAD requests are blocked and make the run fail.
- Input layout and recording metadata remain unchanged during the run.

Selectors come from the pinned upstream page objects and implementation, listed in `report.selectorSources`. No React store is modified or inspected. No API fixture supplies fabricated messages or task success.

All scenarios use one frozen SO101 MCAP. Data-source replacement, different-episode transitions, live ROS connections, command submission, new grasping trials, and long-duration performance remain unverified. Desktop framing still needs human screenshot review. The mobile case accepts reading, playback, and stage navigation; it does not accept every advanced toolbar option or a complete mobile editor.

Each run writes screenshots and `report.json` below ignored `output/`. Failure produces a report and screenshot, preserves the failed step, and exits nonzero. Browser rasterization uses software ANGLE; results are not a GPU performance or 50 Hz measurement. Recorded success is historical evidence, not a new grasping trial.
