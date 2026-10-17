package com.fishbot.station.web;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Set;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;

import com.fishbot.station.service.RuntimeService;

import reactor.core.publisher.Mono;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RuntimeIdentityFilter implements WebFilter {
    private static final Set<HttpMethod> WRITES = Set.of(HttpMethod.POST, HttpMethod.PUT,
            HttpMethod.PATCH, HttpMethod.DELETE);
    private static final byte[] CHANGED = "{\"error\":\"runtime_changed\",\"outcome\":\"rejected\"}"
            .getBytes(StandardCharsets.UTF_8);

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        if (!exchange.getRequest().getPath().value().startsWith("/api/")) return chain.filter(exchange);
        var response = exchange.getResponse();
        response.getHeaders().set(RuntimeService.INSTANCE_HEADER, RuntimeService.instanceId());
        response.getHeaders().set(HttpHeaders.CACHE_CONTROL, "no-store");
        List<String> expected = exchange.getRequest().getHeaders().get(RuntimeService.INSTANCE_HEADER);
        if (WRITES.contains(exchange.getRequest().getMethod()) && expected != null
                && !expected.equals(List.of(RuntimeService.instanceId()))) {
            response.setStatusCode(HttpStatus.CONFLICT);
            response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
            return response.writeWith(Mono.just(response.bufferFactory().wrap(CHANGED)));
        }
        return chain.filter(exchange);
    }
}
