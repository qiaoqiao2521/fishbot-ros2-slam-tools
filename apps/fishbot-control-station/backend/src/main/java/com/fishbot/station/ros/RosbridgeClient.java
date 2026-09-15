package com.fishbot.station.ros;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import jakarta.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;

import com.fishbot.station.config.RosbridgeEndpointProperties;
import com.fishbot.station.config.StationRuntimeProperties;
import com.fasterxml.jackson.databind.ObjectMapper;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;

public class RosbridgeClient {

    private static final Logger log = LoggerFactory.getLogger(RosbridgeClient.class);

    private final String name;
    private final RosbridgeEndpointProperties properties;
    private final StationRuntimeProperties runtimeProperties;
    private final List<RosTopicSubscription> subscriptions;
    private final HttpClient httpClient;
    private final AtomicBoolean connected = new AtomicBoolean(false);
    private final AtomicReference<Instant> lastMessage = new AtomicReference<>(Instant.EPOCH);
    private final Sinks.Many<String> incoming = Sinks.many().multicast().onBackpressureBuffer();
    private final AtomicReference<WebSocket> webSocket = new AtomicReference<>();

    public RosbridgeClient(String name,
                           RosbridgeEndpointProperties properties,
                           StationRuntimeProperties runtimeProperties,
                           ObjectMapper objectMapper,
                           List<RosTopicSubscription> subscriptions) {
        this.name = name;
        this.properties = properties;
        this.runtimeProperties = runtimeProperties;
        this.subscriptions = List.copyOf(subscriptions);
        this.httpClient = HttpClient.newHttpClient();
    }

    @PostConstruct
    public void start() {
        if (runtimeProperties.isOfflineTelemetry()) {
            log.info("Rosbridge client [{}] disabled in offline telemetry mode", name);
            return;
        }
        log.info("Rosbridge client [{}] configured for {}", name, properties.getUrl());
    }

    public boolean isConnected() {
        return connected.get();
    }

    public Instant getLastMessageTime() {
        return lastMessage.get();
    }

    public Flux<String> incomingMessages() {
        return incoming.asFlux();
    }

    public Mono<Void> send(String payload) {
        WebSocket socket = webSocket.get();
        if (!connected.get() || socket == null) {
            return Mono.error(new IllegalStateException("Rosbridge is not connected"));
        }
        log.debug("Sending to rosbridge: {}", payload);
        return Mono.fromCompletionStage(socket.sendText(payload, true)).then();
    }

    @Scheduled(fixedDelayString = "${rosbridge.reconnect-delay-ms:5000}")
    public void ensureConnection() {
        if (runtimeProperties.isOfflineTelemetry()) {
            return;
        }
        if (connected.get()) {
            return;
        }
        connect();
    }

    public void disconnect() {
        if (runtimeProperties.isOfflineTelemetry()) {
            return;
        }
        WebSocket socket = webSocket.getAndSet(null);
        if (socket != null) {
            socket.sendClose(WebSocket.NORMAL_CLOSURE, "shutdown");
        }
        if (connected.compareAndSet(true, false)) {
            log.warn("Rosbridge client [{}] disconnected", name);
        }
    }

    private void connect() {
        if (runtimeProperties.isOfflineTelemetry()) {
            return;
        }
        try {
            httpClient.newWebSocketBuilder()
                    .buildAsync(URI.create(properties.getUrl()), new Listener())
                    .whenComplete((socket, error) -> {
                        if (error != null) {
                            connected.set(false);
                            log.warn("Failed to connect to rosbridge [{}] {}: {}", name, properties.getUrl(), error.getMessage());
                            return;
                        }
                        webSocket.set(socket);
                        connected.set(true);
                        log.info("Connected to rosbridge [{}] {}", name, properties.getUrl());
                        subscriptions.forEach(subscription -> subscribe(subscription.topic(), subscription.type()));
                    });
        } catch (Exception ex) {
            connected.set(false);
            log.warn("Invalid rosbridge URI [{}] {}: {}", name, properties.getUrl(), ex.getMessage());
        }
    }

    private void subscribe(String topic, String type) {
        String payload = String.format(
                "{\"op\":\"subscribe\",\"id\":\"%s\",\"topic\":\"%s\",\"type\":\"%s\",\"queue_length\":1,\"throttle_rate\":0}",
                UUID.randomUUID(), topic, type);
        send(payload).doOnError(err -> log.warn("Failed to subscribe [{}] {}: {}", name, topic, err.getMessage())).subscribe();
    }

    private final class Listener implements WebSocket.Listener {

        private final StringBuilder buffer = new StringBuilder();

        @Override
        public void onOpen(WebSocket webSocket) {
            WebSocket.Listener.super.onOpen(webSocket);
            webSocket.request(1);
        }

        @Override
        public java.util.concurrent.CompletionStage<?> onText(WebSocket webSocket, CharSequence data, boolean last) {
            buffer.append(data);
            if (last) {
                String payload = buffer.toString();
                buffer.setLength(0);
                lastMessage.set(Instant.now());
                incoming.tryEmitNext(payload);
            }
            webSocket.request(1);
            return CompletableFuture.completedFuture(null);
        }

        @Override
        public java.util.concurrent.CompletionStage<?> onClose(WebSocket webSocket, int statusCode, String reason) {
            connected.set(false);
            RosbridgeClient.this.webSocket.compareAndSet(webSocket, null);
            log.warn("Rosbridge [{}] closed: {} {}", name, statusCode, reason);
            return WebSocket.Listener.super.onClose(webSocket, statusCode, reason);
        }

        @Override
        public void onError(WebSocket webSocket, Throwable error) {
            connected.set(false);
            RosbridgeClient.this.webSocket.compareAndSet(webSocket, null);
            log.warn("Rosbridge [{}] error: {}", name, error.getMessage());
        }

    }
}
