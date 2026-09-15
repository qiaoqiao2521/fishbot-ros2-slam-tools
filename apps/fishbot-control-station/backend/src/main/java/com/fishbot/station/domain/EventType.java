package com.fishbot.station.domain;

public enum EventType {
    CONNECTION("connection"),
    ROBOT_STATE("robot-state"),
    NAVIGATION_STATE("navigation-state"),
    PERCEPTION_STATE("perception-state"),
    DIAGNOSTIC("diagnostic");

    private final String value;

    EventType(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }
}
