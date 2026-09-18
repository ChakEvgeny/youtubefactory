import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';
import {theme} from '../theme';

export type OverlayProps = {
  lines: string[];
  kicker?: string;
  side?: 'left' | 'right';
  pos?: 'lower' | 'upper';
};

/**
 * Титр поверх кадра: панель сбоку, фон прозрачный.
 * Рендерить с альфой: --codec=prores --prores-profile=4444.
 * Кегль крупный намеренно: 12% аудитории смотрит с телевизора.
 */
export const Overlay: React.FC<OverlayProps> = ({lines, kicker, side = 'left', pos = 'lower'}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width, height} = useVideoConfig();

  const IN = 12;
  const OUT = 10;
  const enter = spring({frame, fps, config: theme.spring});
  const exit = interpolate(frame, [durationInFrames - OUT, durationInFrames], [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.quad)});
  const a = enter * exit;
  const dx = (1 - enter) * (side === 'left' ? -60 : 60);

  const margin = Math.round(width * 0.055);
  const box: React.CSSProperties = {
    position: 'absolute',
    [side]: margin,
    [pos === 'lower' ? 'bottom' : 'top']: Math.round(height * 0.10),
    maxWidth: width * 0.42,
    opacity: a,
    transform: `translateX(${dx}px)`,
    // подложка: кадр под титром бывает светлым, без неё текст пропадает
    background: 'linear-gradient(90deg, rgba(8,11,15,0.82) 0%, rgba(8,11,15,0.62) 100%)',
    borderLeft: side === 'left' ? `4px solid ${theme.red}` : undefined,
    borderRight: side === 'right' ? `4px solid ${theme.red}` : undefined,
    padding: `${Math.round(height * 0.028)}px ${Math.round(width * 0.028)}px`,
    backdropFilter: 'blur(3px)',
  } as React.CSSProperties;

  return (
    <AbsoluteFill>
      <div style={box}>
        {kicker ? (
          <div style={{
            fontFamily: theme.fontMono, fontSize: Math.min(22, width / 58), letterSpacing: 5,
            color: theme.accent, textTransform: 'uppercase',
            marginBottom: Math.round(height * 0.018)}}>{kicker}</div>
        ) : null}
        {lines.map((ln, i) => (
          <Row key={i} text={ln} delay={IN * 0.4 + i * 5} first={i === 0} width={width} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

const Row: React.FC<{text: string; delay: number; first: boolean; width: number}> =
({text, delay, first, width}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: theme.spring});
  const chars = Math.floor(interpolate(frame - delay, [0, Math.max(text.length * 0.6, 6)],
    [0, text.length], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(...theme.ease)}));
  return (
    <div style={{
      fontFamily: theme.fontMono,
      fontSize: first ? Math.min(46, width / 30) : Math.min(34, width / 40),
      color: first ? theme.ink : theme.dim,
      letterSpacing: 1.5,
      lineHeight: 1.3,
      opacity: s,
      transform: `translateY(${(1 - s) * 10}px)`,
      whiteSpace: 'pre'}}>
      {text.slice(0, chars)}
    </div>
  );
};
