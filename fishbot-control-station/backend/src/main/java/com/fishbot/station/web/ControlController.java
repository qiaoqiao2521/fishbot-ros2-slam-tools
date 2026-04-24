package com.fishbot.station.web;

import jakarta.validation.Valid;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fishbot.station.domain.ControlCommandRequest;
import com.fishbot.station.service.ControlService;

import reactor.core.publisher.Mono;

@RestController
@RequestMapping("/api/v1/control")
public class ControlController {

    private final ControlService controlService;

    public ControlController(ControlService controlService) {
        this.controlService = controlService;
    }

    @PostMapping("/cmd-vel")
    public Mono<ResponseEntity<Object>> cmdVel(@Valid @RequestBody ControlCommandRequest request) {
        return controlService.sendVelocity(request)
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).build()));
    }

    @PostMapping("/stop")
    public Mono<ResponseEntity<Object>> stop() {
        return controlService.stop()
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).build()));
    }

    @PostMapping("/emergency-stop")
    public Mono<ResponseEntity<Object>> emergencyStop() {
        return controlService.emergencyStop()
                .thenReturn(ResponseEntity.ok().build())
                .onErrorResume(ex -> Mono.just(ResponseEntity.status(503).build()));
    }
}
