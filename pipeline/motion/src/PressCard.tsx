import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Frame } from "./Frame";

// Карточка прессы: скриншот шапки статьи с движением камеры, издание/дата,
// строка источника. Fair use: ≤4с, только под комментарий, источник в описании.
export const PressCard: React.FC<{
  shot: string; outlet?: string; date?: string; headline?: string; palette: string[];
}> = ({ shot, outlet, date, headline, palette }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const [accent, ink] = palette;
  const enter = spring({ frame, fps, config: { damping: 15, stiffness: 120 } });
  const z = interpolate(frame, [0, durationInFrames], [1.0, 1.08], { extrapolateRight: "clamp" });
  const py = interpolate(frame, [0, durationInFrames], [0, -height * 0.05], { extrapolateRight: "clamp" });
  const chip = spring({ frame: frame - 8, fps, config: { damping: 16 } });
  return (
    <Frame palette={palette}>
      <div style={{
        position: "absolute", left: width * 0.10, top: height * 0.12, width: width * 0.80, height: height * 0.80,
        overflow: "hidden", borderRadius: 14, background: "#fff",
        boxShadow: `0 ${height * 0.03}px ${height * 0.08}px rgba(0,0,0,0.6)`,
        opacity: Math.min(enter * 1.3, 1),
        transform: `translateY(${(1 - enter) * 50}px) scale(${0.96 + enter * 0.04}) rotate(-0.4deg)`,
      }}>
        <Img src={/^(https?:|data:)/.test(shot) ? shot : staticFile(shot)} style={{
          width: "100%", display: "block",
          transform: `translateY(${py}px) scale(${z})`, transformOrigin: "50% 15%",
        }} />
      </div>
      {(outlet || date) ? (
        <div style={{
          position: "absolute", left: width * 0.10, top: height * 0.065,
          display: "flex", gap: 14, alignItems: "center",
          opacity: Math.min(chip * 1.3, 1), transform: `translateY(${(1 - chip) * 16}px)`,
          fontFamily: "Inter, DejaVu Sans, sans-serif",
        }}>
          <span style={{ background: accent, color: "#fff", fontWeight: 800, fontSize: height * 0.03,
                         padding: `${height * 0.006}px ${height * 0.016}px`, borderRadius: 6 }}>{outlet}</span>
          <span style={{ color: ink, opacity: 0.7, fontSize: height * 0.028, fontWeight: 600 }}>{date}</span>
        </div>
      ) : null}
      {headline ? (
        <div style={{
          position: "absolute", left: width * 0.10, right: width * 0.10, bottom: height * 0.035,
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.022, color: ink, opacity: 0.55,
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>Source: {headline}</div>
      ) : null}
    </Frame>
  );
};
