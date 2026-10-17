package com.fishbot.station.web;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fishbot.station.service.RuntimeService;

@RestController
public class RuntimeController {
    private final RuntimeService runtimeService;

    public RuntimeController(RuntimeService runtimeService) {
        this.runtimeService = runtimeService;
    }

    @GetMapping("/api/v1/runtime")
    public Map<String, Object> runtime() {
        return runtimeService.snapshot();
    }
}
