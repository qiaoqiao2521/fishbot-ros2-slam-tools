package com.fishbot.station.domain;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public class ControlCommandRequest {

    private double linearX;
    private double angularZ;
    @NotBlank
    private String source;
    @NotNull
    private Long sequence;

    public double getLinearX() {
        return linearX;
    }

    public void setLinearX(double linearX) {
        this.linearX = linearX;
    }

    public double getAngularZ() {
        return angularZ;
    }

    public void setAngularZ(double angularZ) {
        this.angularZ = angularZ;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

    public Long getSequence() {
        return sequence;
    }

    public void setSequence(Long sequence) {
        this.sequence = sequence;
    }
}
