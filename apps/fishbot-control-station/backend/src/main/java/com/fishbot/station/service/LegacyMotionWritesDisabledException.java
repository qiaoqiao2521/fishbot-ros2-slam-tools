package com.fishbot.station.service;

public class LegacyMotionWritesDisabledException extends IllegalStateException {
    public LegacyMotionWritesDisabledException() {
        super("legacy_motion_writes_disabled");
    }
}
