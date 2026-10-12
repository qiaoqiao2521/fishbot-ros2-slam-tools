package com.fishbot.station.service;

public class RosClockUnavailableException extends IllegalStateException {
    public RosClockUnavailableException() {
        super("ROS simulation clock is unavailable or paused");
    }
}
