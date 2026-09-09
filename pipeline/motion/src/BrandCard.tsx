import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

// Вордмарк рисуется ИЗ НАЗВАНИЯ бренда. Чужие файлы логотипов не используются.
export const brandSchema = {};

export const BrandCard: React.FC<{
  brand: string; effect: "crack" | "fire" | "fall"; palette: string[]; subtitle?: string;
}> = ({ brand, effect, palette, subtitle }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const [accent, ink, bg] = palette;
  const enter = spring({ frame, fps, config: { damping: 14, mass: 0.6 } });
  const t = frame / fps;

  const fall = effect === "fall" ? interpolate(t, [1.2, 3.5], [0, height * 0.55],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  const tilt = effect === "fall" ? interpolate(t, [1.2, 3.5], [0, 9],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  const shake = effect === "crack" && t > 1.0 && t < 1.6 ? Math.sin(t * 90) * 7 : 0;
  const crackOpacity = effect === "crack"
    ? interpolate(t, [1.0, 1.4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;
  const heat = effect === "fire"
    ? interpolate(t, [0.8, 3.0], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 0;

  const size = Math.min(width / (Math.max(brand.length, 4) * 0.62), height * 0.26);

  return (
    <AbsoluteFill style={{ backgroundColor: bg, alignItems: "center", justifyContent: "center" }}>
      {effect === "fire" && (
        <AbsoluteFill style={{
          background: `radial-gradient(circle at 50% 88%, ${accent}${Math.round(heat * 160).toString(16).padStart(2, "0")} 0%, transparent 62%)`,
        }} />
      )}
      <div style={{
        transform: `translateY(${fall}px) rotate(${tilt}deg) translateX(${shake}px) scale(${0.86 + enter * 0.14})`,
        opacity: Math.min(enter * 1.2, 1), position: "relative",
      }}>
        <div style={{
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontWeight: 800, fontSize: size,
          letterSpacing: "-0.03em", color: ink, textTransform: "uppercase",
          padding: "0 40px", borderBottom: `${Math.max(6, size * 0.07)}px solid ${accent}`,
          filter: heat ? `saturate(${1 + heat}) brightness(${1 - heat * 0.25})` : undefined,
        }}>{brand}</div>
        {crackOpacity > 0 && (
          <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none"
            style={{ position: "absolute", inset: 0, opacity: crackOpacity }}>
            <polyline points="48,0 52,26 44,44 56,66 47,100" fill="none"
              stroke={accent} strokeWidth="0.9" />
            <polyline points="52,26 68,32" fill="none" stroke={accent} strokeWidth="0.6" />
            <polyline points="44,44 28,52" fill="none" stroke={accent} strokeWidth="0.6" />
          </svg>
        )}
      </div>
      {subtitle ? (
        <div style={{
          marginTop: height * 0.05, fontFamily: "Inter, DejaVu Sans, sans-serif",
          fontSize: height * 0.05, color: accent, fontWeight: 700, letterSpacing: "0.08em",
          opacity: interpolate(t, [1.6, 2.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
        }}>{subtitle.toUpperCase()}</div>
      ) : null}
    </AbsoluteFill>
  );
};
