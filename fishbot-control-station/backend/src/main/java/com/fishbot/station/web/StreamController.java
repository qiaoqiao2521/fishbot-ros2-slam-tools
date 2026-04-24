package com.fishbot.station.web;

import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fishbot.station.service.EventStreamService;

import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/api/v1/stream")
public class StreamController {

    private final EventStreamService eventStreamService;

    public StreamController(EventStreamService eventStreamService) {
        this.eventStreamService = eventStreamService;
    }

    @GetMapping(value = "/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<Object>> events() {
        return eventStreamService.stream();
    }
}
