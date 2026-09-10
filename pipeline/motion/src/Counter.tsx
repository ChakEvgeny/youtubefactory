import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Frame } from "./Frame";

export const counterSchema = {};

// Счётчик доезжает до финального числа к 80% слота, дальше «дышит» и уходит.
export const Counter: React.FC<{
  from: number; to: number; prefix?: string; suffix?: string; label?: string; palette: string[];
}> = ({ from, to, prefix, suffix, label, palette }) => {
  const frame = useCurrentFrame();
  const { fps, height, durationInFrames } = useVideoConfig();
  const [accent, ink] = palette;
  const enter = spring({ frame, fps, config: { damping: 14, stiffness: 120, mass: 0.7 } });
  const settle = Math.max(Math.round(durationInFrames * 0.8), fps);
  const p = interpolate(frame, [Math.round(fps * 0.25), settle], [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const eased = 1 - Math.pow(1 - p, 4);
  const val = Math.round(from + (to - from) * eased);
  const breathe = 1 + Math.sin((frame / fps) * 2.1) * 0.006;
  const labelIn = spring({ frame: frame - Math.round(fps * 0.35), fps, config: { damping: 16 } });
  return (
    <Frame palette={palette}>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center" }}>
        <div style={{
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontWeight: 900, fontSize: height * 0.23,
          color: accent, letterSpacing: "-0.04em", fontVariantNumeric: "tabular-nums",
          opacity: enter, transform: `translateY(${(1 - enter) * 40}px) scale(${(0.9 + enter * 0.1) * breathe})`,
          textShadow: `0 0 ${height * 0.06}px ${accent}55`,
        }}>{prefix || ""}{val.toLocaleString("en-US")}{suffix || ""}</div>
        {label ? (
          <div style={{
            marginTop: height * 0.03, color: ink, opacity: 0.9 * Math.min(labelIn * 1.2, 1),
            transform: `translateY(${(1 - labelIn) * 18}px)`,
            fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.05, fontWeight: 600,
          }}>{label}</div>
        ) : null}
      </div>
    </Frame>
  );
};
