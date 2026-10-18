package com.fishbot.station.web;

import jakarta.validation.Valid;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fishbot.station.domain.ControlCommandRequest;
import com.fishbot.station.domain.NavigationGoalRequest;
import com.fishbot.station.service.ControlService;
import com.fishbot.station.service.StationStopLatchedException;
import com.fishbot.station.service.RosClockUnavailableException;
import com.fishbot.station.service.LegacyMotionWritesDisabledException;

import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/api/v1/control")
public class ControlController {

    private final ControlService controlService;

    public ControlController(ControlService controlService) {
        this.controlService = controlService;
    }

    private Mono<ResponseEntity<Object>> disabled(LegacyMotionWritesDisabledException error) {
        return Mono.just(ResponseEntity.status(409).body(java.util.Map.of(
                "error", "legacy_motion_writes_disabled", "outcome", "rejected")));
    }

    @PostMapping("/cmd-vel")
    public Mono<ResponseEntity<Object>> cmdVel(@Valid @RequestBody ControlCommandRequest request) {
        return controlService.sendVelocity(request)
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(LegacyMotionWritesDisabledException.class, this::disabled)
                .onErrorResume(IllegalArgumentException.class, ex -> Mono.just(ResponseEntity.badRequest().body(java.util.Map.of("error", "invalid_velocity"))))
                .onErrorResume(StationStopLatchedException.class, ex -> Mono.just(ResponseEntity.status(409).body(java.util.Map.of("error", "station_stop_latched"))))
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).body(java.util.Map.of("error", "rosbridge_unavailable"))));
    }

    @PostMapping("/goal")
    public Mono<ResponseEntity<Object>> goal(@Valid @RequestBody NavigationGoalRequest request) {
        return controlService.sendNavigationGoal(request)
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(LegacyMotionWritesDisabledException.class, this::disabled)
                .onErrorResume(IllegalArgumentException.class, ex -> Mono.just(ResponseEntity.badRequest().body(java.util.Map.of("error", "invalid_goal"))))
                .onErrorResume(StationStopLatchedException.class, ex -> Mono.just(ResponseEntity.status(409).body(java.util.Map.of("error", "station_stop_latched"))))
                .onErrorResume(RosClockUnavailableException.class, ex -> Mono.just(ResponseEntity.status(503).body(java.util.Map.of("error", "clock_unavailable"))))
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).body(java.util.Map.of("error", "rosbridge_unavailable"))));
    }

    @PostMapping("/initial-pose")
    public Mono<ResponseEntity<Object>> initialPose(@Valid @RequestBody NavigationGoalRequest request) {
        return controlService.sendInitialPose(request)
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(LegacyMotionWritesDisabledException.class, this::disabled)
                .onErrorResume(IllegalArgumentException.class, ex -> Mono.just(ResponseEntity.badRequest().body(java.util.Map.of("error", "invalid_initial_pose"))))
                .onErrorResume(StationStopLatchedException.class, ex -> Mono.just(ResponseEntity.status(409).body(java.util.Map.of("error", "station_stop_latched"))))
                .onErrorResume(RosClockUnavailableException.class, ex -> Mono.just(ResponseEntity.status(503).body(java.util.Map.of("error", "clock_unavailable"))))
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).body(java.util.Map.of("error", "rosbridge_unavailable"))));
    }

    @PostMapping("/stop")
    public Mono<ResponseEntity<Object>> stop() {
        return controlService.stop()
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(LegacyMotionWritesDisabledException.class, this::disabled)
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).build()));
    }

    @PostMapping("/emergency-stop")
    public Mono<ResponseEntity<Object>> emergencyStop() {
        return controlService.emergencyStop()
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(LegacyMotionWritesDisabledException.class, this::disabled)
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).build()));
    }
}
