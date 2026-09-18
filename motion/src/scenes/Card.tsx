import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';
import {theme} from '../theme';
import {Grain} from '../components/Grain';
import {Vignette} from '../components/Vignette';

export type CardProps = {lines: string[]; kicker?: string; mono?: boolean};

/** Карточка-документ: строки печатаются по очереди, под ними прочерк. */
export const Card: React.FC<CardProps> = ({lines, kicker, mono = true}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width} = useVideoConfig();
  const out = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.quad)});

  // лёгкое дыхание, чтобы кадр не стоял мёртво
  const breathe = 1 + 0.006 * Math.sin((frame / fps) * 1.1);

  return (
    <AbsoluteFill style={{backgroundColor: theme.bg}}>
      <AbsoluteFill style={{
        background: 'radial-gradient(120% 80% at 50% 40%, #131b24 0%, #0B0F14 70%)'}} />
      <AbsoluteFill style={{
        justifyContent: 'center', alignItems: 'center', opacity: out,
        transform: `scale(${breathe})`}}>
        {kicker ? (
          <Kicker text={kicker} delay={2} />
        ) : null}
        {lines.map((ln, i) => (
          <Line key={i} text={ln} delay={6 + i * 7} big={i === 0} mono={mono} width={width} />
        ))}
        <Rule delay={6 + lines.length * 7} />
      </AbsoluteFill>
      <Vignette />
      <Grain opacity={0.045} />
    </AbsoluteFill>
  );
};

const Kicker: React.FC<{text: string; delay: number}> = ({text, delay}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: theme.spring});
  return (
    <div style={{
      fontFamily: theme.fontMono, fontSize: 26, letterSpacing: 6, color: theme.accent,
      opacity: s, transform: `translateY(${(1 - s) * 14}px)`, marginBottom: 26,
      textTransform: 'uppercase'}}>{text}</div>
  );
};

/** Печать по символам плюс подъезд и лёгкий масштаб — одна анимация из трёх свойств. */
const Line: React.FC<{text: string; delay: number; big: boolean; mono: boolean; width: number}> =
({text, delay, big, mono, width}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: theme.spring});
  const chars = Math.floor(interpolate(frame - delay, [0, Math.max(text.length * 0.7, 8)],
    [0, text.length], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(...theme.ease)}));
  const shown = text.slice(0, chars);
  const caret = chars < text.length && Math.floor(frame / 6) % 2 === 0;
  return (
    <div style={{
      fontFamily: mono ? theme.fontMono : theme.fontSans,
      fontSize: big ? Math.min(64, width / 22) : Math.min(40, width / 34),
      color: big ? theme.ink : theme.dim,
      letterSpacing: big ? 2 : 1,
      opacity: s, transform: `translateY(${(1 - s) * 18}px) scale(${0.985 + 0.015 * s})`,
      marginBottom: 14, textAlign: 'center', maxWidth: width * 0.8, lineHeight: 1.25}}>
      {shown}{caret ? '▍' : ''}
    </div>
  );
};

const Rule: React.FC<{delay: number}> = ({delay}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: {damping: 200, stiffness: 90, mass: 0.9}});
  return (
    <div style={{height: 4, width: 260 * s, backgroundColor: theme.red, marginTop: 24,
      opacity: s}} />
  );
};
