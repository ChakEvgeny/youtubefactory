import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame,
  useVideoConfig, Easing} from 'remotion';

/** Оформление канала The Case Room (нуар-комикс × ризограф), 2026-09-18.
 *
 *  Концепция B «Три панели»: панели комикса прорезаются тушью, затем удар жёлтой
 *  плашки рассказчика с названием — тот же язык, что на баннере и иконке.
 *  Граница блока — следующая панель въезжает через чёрный зазор (NoirCut).
 *  Инфографика — карточка из дела (Evidence), не отдельный экран. */
export const PAPER = '#EDE3CD';
export const INK = '#141210';
export const YEL = '#E2B228';
export const STEEL = '#5E6E7A';
const ANTON = 'Anton, Impact, sans-serif';
const TYPE = '"Special Elite", monospace';
const ease = Easing.bezier(0.33, 0, 0.2, 1);

const Grain: React.FC<{o?: number}> = ({o = 0.08}) => (
  <AbsoluteFill style={{
    opacity: o, mixBlendMode: 'multiply', pointerEvents: 'none',
    backgroundImage: 'radial-gradient(#6b5f50 1px, transparent 1px), radial-gradient(#6b5f50 1px, transparent 1px)',
    backgroundSize: '5px 5px, 9px 9px', backgroundPosition: '0 0, 3px 4px',
  }} />
);

/** Плашка рассказчика: жёлтый прямоугольник, толстая чёрная рамка, сдвинутая тень. */
export const Caption: React.FC<{title: string; sub?: string; size: number; pop: number}> =
  ({title, sub, size, pop}) => (
    <div style={{
      transform: `scale(${interpolate(pop, [0, 1], [1.35, 1])}) rotate(-1.2deg)`,
      opacity: Math.min(pop * 3, 1),
      background: YEL, border: `${size * 0.07}px solid ${INK}`,
      boxShadow: `${size * 0.12}px ${size * 0.12}px 0 ${INK}`,
      padding: `${size * 0.16}px ${size * 0.42}px ${size * 0.2}px`, textAlign: 'center',
    }}>
      <div style={{fontFamily: ANTON, fontSize: size, color: INK, lineHeight: 1, letterSpacing: '0.01em'}}>{title}</div>
      {sub ? <div style={{fontFamily: TYPE, fontSize: size * 0.24, color: INK, marginTop: size * 0.12,
        letterSpacing: '0.08em'}}>{sub}</div> : null}
    </div>
  );

/** Панель, прорезаемая тушью сверху вниз: край неровный, как мазок кисти. */
const Panel: React.FC<{src: string; x: number; y: number; w: number; h: number; from: number}> =
  ({src, x, y, w, h, from}) => {
    const frame = useCurrentFrame();
    const p = interpolate(frame, [from, from + 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
    if (p <= 0) return null;
    const pts: string[] = [];
    const n = 16;
    for (let i = 0; i <= n; i++) {
      const jag = Math.sin(i * 2.7 + from) * 1.6;
      pts.push(`${(i / n) * 100}% ${Math.min(p * 104 + jag * (1 - p), 100)}%`);
    }
    return (
      <div style={{position: 'absolute', left: x, top: y, width: w, height: h, background: INK,
        clipPath: `polygon(0% 0%, 100% 0%, ${pts.reverse().join(',')})`}}>
        <Img src={staticFile(src)} style={{position: 'absolute', inset: 10, width: w - 20, height: h - 20,
          objectFit: 'cover', transform: `scale(${1.08 - 0.08 * p})`}} />
      </div>
    );
  };

export type NoirIntroProps = {title?: string; sub?: string};

export const NoirIntro: React.FC<NoirIntroProps> = ({title = 'THE CASE ROOM', sub = 'TRUE CASES · FRAUD · HEISTS · CONS'}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps, durationInFrames} = useVideoConfig();
  const pw = W * 0.29, ph = H * 0.84, gap = W * 0.022;
  const x0 = (W - (3 * pw + 2 * gap)) / 2, y0 = (H - ph) / 2;
  const starts = [4, 13, 22];
  const capAt = 36;
  const pop = spring({frame: frame - capAt, fps, config: {damping: 11, stiffness: 180, mass: 0.7}});
  const push = interpolate(frame, [0, durationInFrames], [1, 1.045]);
  const out = interpolate(frame, [durationInFrames - 6, durationInFrames], [1, 0], {extrapolateLeft: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: PAPER, opacity: out}}>
      <AbsoluteFill style={{transform: `scale(${push})`}}>
        {['noir/panel1.jpg', 'noir/panel2.jpg', 'noir/panel3.jpg'].map((s, i) => (
          <Panel key={s} src={s} x={x0 + i * (pw + gap)} y={y0} w={pw} h={ph} from={starts[i]} />
        ))}
        {/* гаснут только панели, бумага между ними остаётся чистой */}
        <div style={{position: 'absolute', left: x0, top: y0, width: 3 * pw + 2 * gap, height: ph,
          background: INK, opacity: 0.45 * Math.min(Math.max(pop, 0), 1),
          maskImage: `linear-gradient(90deg, #000 0 ${pw}px, transparent ${pw}px ${pw + gap}px, #000 ${pw + gap}px ${2 * pw + gap}px, transparent ${2 * pw + gap}px ${2 * pw + 2 * gap}px, #000 ${2 * pw + 2 * gap}px)`,
          WebkitMaskImage: `linear-gradient(90deg, #000 0 ${pw}px, transparent ${pw}px ${pw + gap}px, #000 ${pw + gap}px ${2 * pw + gap}px, transparent ${2 * pw + gap}px ${2 * pw + 2 * gap}px, #000 ${2 * pw + 2 * gap}px)`}} />
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
          {frame >= capAt ? <Caption title={title} sub={sub} size={H * 0.15} pop={pop} /> : null}
        </AbsoluteFill>
      </AbsoluteFill>
      <Grain />
      {starts.map((s, i) => (
        <Sequence key={i} from={s}><Audio src={staticFile('noir/thud.mp3')} volume={0.7} /></Sequence>
      ))}
      <Sequence from={capAt}><Audio src={staticFile('noir/stamp.mp3')} /></Sequence>
      <Sequence from={capAt + 2}><Audio src={staticFile('noir/sting.mp3')} volume={0.8} /></Sequence>
    </AbsoluteFill>
  );
};

/** Граница блока: следующая панель въезжает справа через чёрный зазор. */
export type NoirCutProps = {from: string; to: string; zoom?: number; seconds?: number};

export const NoirCut: React.FC<NoirCutProps> = ({from, to, zoom = 1}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H} = useVideoConfig();
  const gap = W * 0.03;
  const t = interpolate(frame, [2, 15], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.6, 0, 0.25, 1)});
  const shift = -(W + gap) * t;
  return (
    <AbsoluteFill style={{backgroundColor: INK, overflow: 'hidden'}}>
      <div style={{position: 'absolute', left: shift, top: 0, width: W, height: H, overflow: 'hidden'}}>
        <Img src={staticFile(from)} style={{width: W, height: H, objectFit: 'cover', transform: `scale(${zoom})`}} />
      </div>
      <div style={{position: 'absolute', left: shift + W + gap, top: 0, width: W, height: H}}>
        <Img src={staticFile(to)} style={{width: W, height: H, objectFit: 'cover'}} />
      </div>
      <Sequence from={1}><Audio src={staticFile('noir/slide.mp3')} volume={0.8} /></Sequence>
    </AbsoluteFill>
  );
};

/** Аутро: последний кадр сжимается в панель, гаснет, удар плашки THE END. */
export type NoirOutroProps = {last?: string; zoom?: number; seconds?: number; channel?: string};

export const NoirOutro: React.FC<NoirOutroProps> = ({last, zoom = 1, channel = 'THE CASE ROOM'}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps} = useVideoConfig();
  const s = interpolate(frame, [4, 22], [1, 0.7], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  const dim = interpolate(frame, [18, 34], [1, 0.3], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const capAt = 34;
  const pop = spring({frame: frame - capAt, fps, config: {damping: 11, stiffness: 180, mass: 0.7}});
  const sub = interpolate(frame, [capAt + 12, capAt + 24], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: PAPER}}>
      {last ? (
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
          <div style={{width: W, height: H, transform: `scale(${s})`, border: `${12 / s}px solid ${INK}`,
            overflow: 'hidden', boxSizing: 'border-box'}}>
            <Img src={staticFile(last)} style={{width: '100%', height: '100%', objectFit: 'cover',
              transform: `scale(${zoom})`, filter: `brightness(${dim})`}} />
          </div>
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', flexDirection: 'column'}}>
        {frame >= capAt ? <Caption title="THE END" size={H * 0.16} pop={pop} /> : null}
        <div style={{marginTop: H * 0.06, fontFamily: TYPE, fontSize: H * 0.04, color: PAPER,
          letterSpacing: '0.2em', opacity: sub}}>{channel}</div>
      </AbsoluteFill>
      <Grain />
      <Sequence from={3}><Audio src={staticFile('noir/slide.mp3')} volume={0.7} /></Sequence>
      <Sequence from={capAt}><Audio src={staticFile('noir/stamp.mp3')} /></Sequence>
      <Sequence from={capAt + 2}><Audio src={staticFile('noir/sting.mp3')} volume={0.8} /></Sequence>
    </AbsoluteFill>
  );
};
