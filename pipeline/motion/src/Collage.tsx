import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Frame } from "./Frame";

// Коллаж: фон канала (Frame), вырезанный объект с пружиной и параллаксом,
// кинетический текст-факт, строка атрибуции в углу для CC-BY / CC-BY-SA.
export const Collage: React.FC<{
  cutout: string; text?: string; sub?: string; attribution?: string; palette: string[];
  side?: "left" | "right"; objectScale?: number; portrait?: boolean; mode?: "cutout" | "photo";
}> = ({ cutout, text, sub, attribution, palette, side = "right", objectScale = 1, portrait, mode = "cutout" }) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const [accent, ink] = palette;
  const t = frame / fps;
  const enter = spring({ frame, fps, config: { damping: 13, stiffness: 110, mass: 0.8 } });
  // параллакс: объект дрейфует медленнее «камеры», текст быстрее
  const camX = interpolate(frame, [0, durationInFrames], [0, -26], { extrapolateRight: "clamp" });
  const camY = Math.sin(t * 0.6) * 6;
  const objH = height * (portrait ? 0.78 : 0.62) * objectScale;
  const objX = side === "right" ? width * 0.56 : width * 0.06;
  const words = (text || "").split(/\s+/).filter(Boolean);
  const textX = side === "right" ? width * 0.07 : width * 0.52;

  return (
    <Frame palette={palette}>
      {/* мягкое пятно под объектом */}
      <div style={{
        position: "absolute", left: objX - 40, top: height * 0.16, width: width * 0.42, height: height * 0.72,
        background: `radial-gradient(ellipse at 50% 60%, ${accent}22 0%, transparent 65%)`,
        transform: `translate(${camX * 0.4}px, ${camY * 0.4}px)`,
      }} />
      {mode === "photo" ? (
        <div style={{
          position: "absolute", left: side === "right" ? width * 0.50 : width * 0.05, top: height * 0.14,
          width: width * 0.45, height: height * 0.72, overflow: "hidden", borderRadius: 10,
          background: "#000", boxShadow: `0 ${height * 0.03}px ${height * 0.07}px rgba(0,0,0,0.6)`,
          border: `2px solid ${ink}22`,
          opacity: Math.min(enter * 1.4, 1),
          transform: `translate(${camX * 0.7}px, ${camY * 0.7 + (1 - enter) * 50}px) rotate(${(1 - enter) * -1.5 + (side === "right" ? 0.6 : -0.6)}deg)`,
        }}>
          <Img src={/^(https?:|data:)/.test(cutout) ? cutout : staticFile(cutout)} style={{
            width: "100%", height: "100%", objectFit: "cover", display: "block",
            transform: `scale(${1.04 + interpolate(frame, [0, durationInFrames], [0, 0.07], { extrapolateRight: "clamp" })})`,
            transformOrigin: "50% 40%",
          }} />
        </div>
      ) : (
      <div style={{
        position: "absolute", left: objX, top: height * 0.5, height: objH,
        transform: `translate(${camX * 0.7}px, ${camY * 0.7 - objH / 2 + (1 - enter) * 60}px) ` +
                   `scale(${0.92 + enter * 0.08}) rotate(${(1 - enter) * -2}deg)`,
        opacity: Math.min(enter * 1.4, 1),
        filter: `drop-shadow(0 ${height * 0.03}px ${height * 0.05}px rgba(0,0,0,0.55)) drop-shadow(0 2px 0 ${ink}22)`,
      }}>
        <Img src={/^(https?:|data:)/.test(cutout) ? cutout : staticFile(cutout)} style={{ height: "100%", width: "auto", display: "block" }} />
      </div>
      )}
      {/* кинетический текст: слова входят со стаггером */}
      <div style={{
        position: "absolute", left: textX, top: height * 0.30, width: width * 0.40,
        transform: `translate(${camX * 1.3}px, ${camY * 1.2}px)`,
        fontFamily: "Inter, DejaVu Sans, sans-serif", fontWeight: 900, color: ink,
        fontSize: height * (words.length > 6 ? 0.075 : 0.095), lineHeight: 1.05, letterSpacing: "-0.02em",
      }}>
        {words.map((w, i) => {
          const s = spring({ frame: frame - 6 - i * 3, fps, config: { damping: 14, stiffness: 140 } });
          return (
            <span key={i} style={{
              display: "inline-block", marginRight: "0.28em", opacity: Math.min(s * 1.3, 1),
              transform: `translateY(${(1 - s) * 28}px)`,
              color: /\d|£|\$|%/.test(w) ? accent : ink,
            }}>{w}</span>
          );
        })}
        {sub ? (
          <div style={{
            marginTop: height * 0.02, fontSize: height * 0.036, fontWeight: 600, color: ink, opacity: 0.75,
            transform: `translateY(${(1 - spring({ frame: frame - 18, fps, config: { damping: 16 } })) * 14}px)`,
          }}>{sub}</div>
        ) : null}
      </div>
      {attribution ? (
        <div style={{
          position: "absolute", right: height * 0.03, bottom: height * 0.025,
          fontFamily: "Inter, DejaVu Sans, sans-serif", fontSize: height * 0.02, color: ink, opacity: 0.55,
        }}>{attribution}</div>
      ) : null}
    </Frame>
  );
};
