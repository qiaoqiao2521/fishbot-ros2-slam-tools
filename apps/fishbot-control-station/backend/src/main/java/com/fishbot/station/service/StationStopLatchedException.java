package com.fishbot.station.service;

public class StationStopLatchedException extends IllegalStateException {
    public StationStopLatchedException() {
        super("Station stop is latched; restart after checking other velocity publishers");
    }
}
