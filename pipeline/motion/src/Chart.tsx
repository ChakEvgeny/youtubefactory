import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

export const chartSchema = {};

export const Chart: React.FC<{
  title?: string; points: number[]; labels?: string[]; palette: string[]; unit?: string;
}> = ({ title, points, labels = [], palette, unit }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const [accent, ink, bg] = palette;
  const p = interpolate(frame / fps, [0.4, 3.2], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  const pad = { l: width * 0.12, r: width * 0.08, t: height * 0.26, b: height * 0.18 };
  const cw = width - pad.l - pad.r, chh = height - pad.t - pad.b;
  const max = Math.max(...points), min = Math.min(...points);
  const span = Math.max(max - min, 1e-6);
  const xy = points.map((v, i) => [
    pad.l + (cw * i) / Math.max(points.length - 1, 1),
    pad.t + chh - ((v - min) / span) * chh,
  ]);
  const shown = Math.max(2, Math.ceil(xy.length * p));
  const path = xy.slice(0, shown).map((c, i) => `${i ? "L" : "M"}${c[0]},${c[1]}`).join(" ");
  const last = xy[shown - 1];
  const falling = points[points.length - 1] < points[0];

  return (
    <AbsoluteFill style={{ backgroundColor: bg }}>
      {title ? (
        <div style={{
          position: "absolute", top: height * 0.09, left: pad.l, color: ink,
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.062, fontWeight: 800,
        }}>{title}</div>
      ) : null}
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <line x1={pad.l} y1={pad.t + chh} x2={pad.l + cw} y2={pad.t + chh}
          stroke={ink} strokeOpacity="0.25" strokeWidth="3" />
        <path d={path} fill="none" stroke={accent} strokeWidth="9"
          strokeLinecap="round" strokeLinejoin="round" />
        {last && (
          <>
            <circle cx={last[0]} cy={last[1]} r="16" fill={accent} />
            {falling && (
              <polygon
                points={`${last[0]},${last[1] + 92} ${last[0] - 34},${last[1] + 30} ${last[0] + 34},${last[1] + 30}`}
                fill={accent} opacity={interpolate(p, [0.75, 1], [0, 1], { extrapolateLeft: "clamp" })} />
            )}
          </>
        )}
      </svg>
      <div style={{
        position: "absolute", right: pad.r, top: height * 0.09, color: accent,
        fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.075, fontWeight: 800,
      }}>
        {points[points.length - 1].toLocaleString("en-US")}{unit || ""}
      </div>
      {labels.length ? (
        <div style={{
          position: "absolute", left: pad.l, right: pad.r, bottom: height * 0.08,
          display: "flex", justifyContent: "space-between", color: ink, opacity: 0.65,
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.032,
        }}>{labels.map((l, i) => <span key={i}>{l}</span>)}</div>
      ) : null}
    </AbsoluteFill>
  );
};
