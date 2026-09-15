package com.fishbot.station.web;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fishbot.station.domain.ConnectionSnapshot;
import com.fishbot.station.domain.DiagnosticSnapshot;
import com.fishbot.station.domain.NavigationRuntimeSnapshot;
import com.fishbot.station.domain.PerceptionRuntimeSnapshot;
import com.fishbot.station.domain.RobotStateSnapshot;
import com.fishbot.station.service.ConnectionStateService;
import com.fishbot.station.service.DiagnosticsService;
import com.fishbot.station.service.NavigationStateService;
import com.fishbot.station.service.PerceptionStateService;
import com.fishbot.station.service.RobotStateService;

@RestController
@RequestMapping("/api/v1")
public class StatusController {

    private final ConnectionStateService connectionStateService;
    private final RobotStateService robotStateService;
    private final NavigationStateService navigationStateService;
    private final PerceptionStateService perceptionStateService;
    private final DiagnosticsService diagnosticsService;

    public StatusController(ConnectionStateService connectionStateService,
                            RobotStateService robotStateService,
                            NavigationStateService navigationStateService,
                            PerceptionStateService perceptionStateService,
                            DiagnosticsService diagnosticsService) {
        this.connectionStateService = connectionStateService;
        this.robotStateService = robotStateService;
        this.navigationStateService = navigationStateService;
        this.perceptionStateService = perceptionStateService;
        this.diagnosticsService = diagnosticsService;
    }

    @GetMapping("/connection")
    public ConnectionSnapshot connection() {
        return connectionStateService.snapshot();
    }

    @GetMapping("/state")
    public RobotStateSnapshot state() {
        return robotStateService.getCurrentState();
    }

    @GetMapping("/navigation")
    public NavigationRuntimeSnapshot navigation() {
        return navigationStateService.snapshot();
    }

    @GetMapping("/perception")
    public PerceptionRuntimeSnapshot perception() {
        return perceptionStateService.snapshot();
    }

    @GetMapping("/diagnostics")
    public DiagnosticSnapshot diagnostics() {
        return diagnosticsService.latestSnapshot();
    }
}
