import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

export const counterSchema = {};

export const Counter: React.FC<{
  from: number; to: number; prefix?: string; suffix?: string; label?: string; palette: string[];
}> = ({ from, to, prefix, suffix, label, palette }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();
  const [accent, ink, bg] = palette;
  const t = frame / fps;
  const e = interpolate(t, [0.3, 2.6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const eased = 1 - Math.pow(1 - e, 3);
  const val = Math.round(from + (to - from) * eased);

  return (
    <AbsoluteFill style={{
      backgroundColor: bg, alignItems: "center", justifyContent: "center", flexDirection: "column",
    }}>
      <div style={{
        fontFamily: "Inter, DejaVu Sans, sans-serif", fontWeight: 900, fontSize: height * 0.24,
        color: accent, letterSpacing: "-0.04em", fontVariantNumeric: "tabular-nums",
      }}>
        {prefix || ""}{val.toLocaleString("en-US")}{suffix || ""}
      </div>
      {label ? (
        <div style={{
          marginTop: height * 0.03, color: ink, opacity: 0.85,
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.055, fontWeight: 600,
        }}>{label}</div>
      ) : null}
    </AbsoluteFill>
  );
};
