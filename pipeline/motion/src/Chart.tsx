import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { Frame } from "./Frame";

export const chartSchema = {};

export const Chart: React.FC<{
  title?: string; points: number[]; labels?: string[]; palette: string[]; unit?: string;
}> = ({ title, points, labels = [], palette, unit }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const [accent, ink] = palette;
  const settle = Math.max(Math.round(durationInFrames * 0.75), fps);
  const p = interpolate(frame, [Math.round(fps * 0.3), settle], [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const eased = 1 - Math.pow(1 - p, 3);
  const titleIn = spring({ frame, fps, config: { damping: 15 } });

  const pad = { l: width * 0.12, r: width * 0.08, t: height * 0.27, b: height * 0.18 };
  const cw = width - pad.l - pad.r, chh = height - pad.t - pad.b;
  const max = Math.max(...points), min = Math.min(...points);
  const span = Math.max(max - min, 1e-6);
  const xy = points.map((v, i) => [
    pad.l + (cw * i) / Math.max(points.length - 1, 1),
    pad.t + chh - ((v - min) / span) * chh,
  ]);
  // линия «рисуется» по длине пути через stroke-dasharray
  const len = xy.slice(1).reduce((a, c, i) => a + Math.hypot(c[0] - xy[i][0], c[1] - xy[i][1]), 0);
  const path = xy.map((c, i) => `${i ? "L" : "M"}${c[0]},${c[1]}`).join(" ");
  const last = xy[xy.length - 1];
  const falling = points[points.length - 1] < points[0];
  const dotIn = spring({ frame: frame - settle + 6, fps, config: { damping: 9, stiffness: 160 } });

  return (
    <Frame palette={palette}>
      {title ? (
        <div style={{
          position: "absolute", top: height * 0.09, left: pad.l, color: ink,
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.06, fontWeight: 800,
          opacity: titleIn, transform: `translateY(${(1 - titleIn) * 24}px)`,
        }}>{title}</div>
      ) : null}
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <line x1={pad.l} y1={pad.t + chh} x2={pad.l + cw} y2={pad.t + chh}
          stroke={ink} strokeOpacity="0.22" strokeWidth="3" />
        <path d={path} fill="none" stroke={accent} strokeWidth="9" strokeLinecap="round"
          strokeLinejoin="round" strokeDasharray={len} strokeDashoffset={len * (1 - eased)}
          style={{ filter: `drop-shadow(0 0 12px ${accent}66)` }} />
        {p >= 0.99 && (
          <>
            <circle cx={last[0]} cy={last[1]} r={16 * Math.min(dotIn, 1.15)} fill={accent} />
            {falling && (
              <polygon
                points={`${last[0]},${last[1] + 92} ${last[0] - 34},${last[1] + 30} ${last[0] + 34},${last[1] + 30}`}
                fill={accent} opacity={Math.min(dotIn, 1)}
                transform={`translate(0 ${(1 - Math.min(dotIn, 1)) * -18})`} />
            )}
          </>
        )}
      </svg>
      <div style={{
        position: "absolute", right: pad.r, top: height * 0.09, color: accent,
        fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.075, fontWeight: 800,
        opacity: Math.min(dotIn, 1), transform: `scale(${0.85 + Math.min(dotIn, 1) * 0.15})`,
      }}>{points[points.length - 1].toLocaleString("en-US")}{unit || ""}</div>
      {labels.length ? (
        <div style={{
          position: "absolute", left: pad.l, right: pad.r, bottom: height * 0.08,
          display: "flex", justifyContent: "space-between", color: ink, opacity: 0.65,
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.032,
        }}>{labels.map((l, i) => (
          <span key={i} style={{ opacity: interpolate(frame, [fps * 0.2 + i * 4, fps * 0.5 + i * 4], [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>{l}</span>))}</div>
      ) : null}
    </Frame>
  );
};
