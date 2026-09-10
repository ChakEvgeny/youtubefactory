import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

// Пятислойный стек по remotion-motion-graphics:
// фон-меш → (ассеты/графика — children) → цветокоррекция → зерно + виньетка.
// Плоская заливка запрещена: отсюда «дешёвый» вид старых композиций.
export const Frame: React.FC<{ palette: string[]; children: React.ReactNode; exitAt?: number }> =
  ({ palette, children, exitAt }) => {
    const frame = useCurrentFrame();
    const { fps, durationInFrames } = useVideoConfig();
    const [accent, , bg] = palette;
    const t = frame / fps;
    // уход быстрее появления: последние 10 кадров
    const exitStart = exitAt ?? durationInFrames - 10;
    const exit = interpolate(frame, [exitStart, durationInFrames], [1, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    // дыхание фона — медленный дрейф пятен
    const dx = Math.sin(t * 0.35) * 4, dy = Math.cos(t * 0.27) * 3;
    return (
      <AbsoluteFill style={{ backgroundColor: bg, overflow: "hidden" }}>
        <AbsoluteFill style={{
          background: `radial-gradient(ellipse at ${38 + dx}% ${30 + dy}%, ${accent}26 0%, transparent 55%),` +
                      `radial-gradient(ellipse at ${72 - dx}% ${78 - dy}%, #ffffff10 0%, transparent 50%)`,
        }} />
        <AbsoluteFill style={{ opacity: exit, transform: `scale(${0.985 + exit * 0.015})` }}>
          {children}
        </AbsoluteFill>
        <AbsoluteFill style={{ background: "linear-gradient(180deg, #ffffff06, transparent 40%, #00000030)", mixBlendMode: "soft-light" }} />
        <AbsoluteFill style={{
          backgroundImage: "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23n)' opacity='0.55'/></svg>\")",
          opacity: 0.07, mixBlendMode: "overlay",
          transform: `translate(${(frame % 3) * 2}px, ${(frame % 2) * -2}px)`,
        }} />
        <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, transparent 55%, #00000088 100%)" }} />
      </AbsoluteFill>
    );
  };
