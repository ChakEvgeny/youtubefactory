import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';

/** Финальный кадр объясняющего ролика.
 *
 *  Правило Евгения 2026-09-17: ролик не обрывается на последнем слове, и финал
 *  одинаковый во всех видео канала. Последний рисунок уходит в чёрное, на нём
 *  выезжает плашка THE END, под ней — благодарность и призыв подписаться.
 *
 *  Лежит поверх кадра альфой, как и схемы: отдельного видеофайла не делаем. */
const C = {paper: '#F2E9D8', ink: '#141210', accent: '#E2503C', black: '#0A0908'};
const K = (h: number, f: number) => Math.round(h * f);
const FONT = '"DejaVu Sans", system-ui, sans-serif';
const ease = Easing.bezier(0.22, 1, 0.36, 1);

export type OutroProps = {
  font?: string;
  end?: string;
  thanks?: string;
  cta?: string;
  /** доля длительности, за которую рисунок уходит в чёрное */
  fade?: number;
};

export const Outro: React.FC<OutroProps> = ({font, end, thanks, cta, fade = 0.35}) => {
  const frame = useCurrentFrame();
  const {height, width, durationInFrames, fps} = useVideoConfig();
  const dark = Math.max(Math.round(durationInFrames * fade), 10);

  // 1. Рисунок под нами затемняется.
  const veil = interpolate(frame, [0, dark], [0, 1], {
    extrapolateRight: 'clamp', easing: ease,
  });
  // 2. Плашка выезжает, когда чернота уже плотная.
  const pop = spring({frame: frame - dark, fps, config: {damping: 200, stiffness: 110, mass: 0.8}});
  // 3. Строки под плашкой проявляются последними.
  const text = interpolate(frame, [dark + fps * 0.45, dark + fps * 1.1], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease,
  });

  return (
    <AbsoluteFill style={{fontFamily: font || FONT}}>
      <AbsoluteFill style={{backgroundColor: C.black, opacity: veil}} />
      <AbsoluteFill style={{
        alignItems: 'center', justifyContent: 'center', flexDirection: 'column',
      }}>
        <div style={{
          opacity: pop,
          transform: `scale(${interpolate(pop, [0, 1], [0.86, 1])})`,
          padding: `${K(height, 0.045)}px ${K(height, 0.11)}px`,
          background: C.paper,
          border: `${Math.round(height * 0.007)}px solid ${C.ink}`,
          borderRadius: height * 0.022,
          boxShadow: `${Math.round(height * 0.013)}px ${Math.round(height * 0.013)}px 0 ${C.accent}`,
        }}>
          <div style={{
            fontSize: K(height, 0.105), fontWeight: 800, color: C.ink,
            letterSpacing: '0.02em', lineHeight: 1,
          }}>{end || 'THE END'}</div>
        </div>

        <div style={{
          opacity: text,
          transform: `translateY(${interpolate(text, [0, 1], [height * 0.03, 0])}px)`,
          marginTop: K(height, 0.075), textAlign: 'center',
        }}>
          <div style={{fontSize: K(height, 0.050), fontWeight: 700, color: C.paper}}>
            {thanks || 'Thanks for watching'}
          </div>
          <div style={{
            marginTop: K(height, 0.022), fontSize: K(height, 0.044),
            fontWeight: 800, color: C.accent,
          }}>{cta || 'Subscribe for more'}</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
