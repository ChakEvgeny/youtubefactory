import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Frame } from "./Frame";

export const calloutSchema = {};

export const Callout: React.FC<{ text: string; note?: string; palette: string[] }> =
  ({ text, note, palette }) => {
    const frame = useCurrentFrame();
    const { fps, height, width } = useVideoConfig();
    const [accent, ink, bg] = palette;
    const s = spring({ frame, fps, config: { damping: 16 } });
    const wipe = interpolate(frame / fps, [0.2, 1.0], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

    return (
      <Frame palette={palette}><AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{
          transform: `scale(${0.9 + s * 0.1})`, opacity: Math.min(s * 1.3, 1),
          maxWidth: width * 0.78, borderLeft: `${height * 0.02}px solid ${accent}`,
          padding: `${height * 0.05}px ${height * 0.06}px`,
          background: "rgba(255,255,255,0.04)", position: "relative", overflow: "hidden",
        }}>
          <div style={{
            position: "absolute", inset: 0, background: accent, opacity: 0.14,
            transform: `scaleX(${wipe})`, transformOrigin: "left",
          }} />
          <div style={{
            position: "relative", color: ink, fontFamily: "Inter, DejaVu Sans, sans-serif",
            fontSize: height * 0.085, fontWeight: 800, lineHeight: 1.15,
          }}>{text}</div>
          {note ? (
            <div style={{
              position: "relative", marginTop: height * 0.025, color: accent,
              fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.042, fontWeight: 600,
            }}>{note}</div>
          ) : null}
        </div>
      </AbsoluteFill></Frame>
    );
  };
