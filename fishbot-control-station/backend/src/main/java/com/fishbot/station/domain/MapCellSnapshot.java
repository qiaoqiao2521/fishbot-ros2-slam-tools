package com.fishbot.station.domain;

public record MapCellSnapshot(
        int x,
        int y,
        int occupancy) {
}
