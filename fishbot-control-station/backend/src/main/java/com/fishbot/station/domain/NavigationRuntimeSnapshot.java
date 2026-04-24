package com.fishbot.station.domain;

public record NavigationRuntimeSnapshot(
        MapRuntimeSnapshot map,
        TfRuntimeSnapshot tf,
        LocalizationRuntimeSnapshot localization,
        NavStatusRuntimeSnapshot navStatus) {
}
