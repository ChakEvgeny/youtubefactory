import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';

/** Палитра рисовки c2_bright: кремовая бумага, берлинская лазурь, коралл, тушь. */
const C = {
  paper: '#F2E9D8',
  ink: '#141210',
  sea: '#0E86C4',
  accent: '#E2503C',
  dim: '#6E655C',
};
const K = (h: number, f: number) => Math.round(h * f);
const FONT = '"DejaVu Sans", system-ui, sans-serif';

export type Item = {label?: string; value?: number; max?: number};
export type DiagramProps = {
  transparent?: boolean;
  font?: string;
  plate?: boolean;
  outline?: boolean;
  kind: 'gauge' | 'split' | 'equation' | 'cell' | 'counter';
  title?: string;
  items?: (Item | string)[];
};

const ease = Easing.bezier(0.22, 1, 0.36, 1);
const cfgSpring = {damping: 200, stiffness: 110, mass: 0.8};

export const Diagram: React.FC<DiagramProps> = ({kind, title, items = [], transparent, font, plate = true, outline}) => {
  const {width, height} = useVideoConfig();
  return (
    <AbsoluteFill style={{backgroundColor: transparent ? 'transparent' : C.paper, fontFamily: font || FONT}}>
      {transparent ? null : <Grain />}
      {/* Плашка рисуется ДО заголовка и накрывает его: раньше Title шёл первым и
          оставался снаружи плашки, поэтому на штриховке пропадал именно он. */}
      {plate && transparent && !outline ? (
        <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
          <div style={{
            width: '80%', height: title ? '68%' : '58%', borderRadius: height * 0.03,
            background: 'rgba(242,233,216,0.94)',
            border: `${Math.round(height * 0.006)}px solid ${C.ink}`,
            boxShadow: `${Math.round(height*0.012)}px ${Math.round(height*0.012)}px 0 ${C.ink}`,
          }} />
        </AbsoluteFill>
      ) : null}
      {title ? <Title text={title} width={width} /> : null}
      {/* Содержимое ужимается под число строк. Раньше размеры были константами,
          и схема на три строки не влезала в плашку: третья шкала вылезала за
          нижний край (подлодка, «What runs out first»). Плашку расширять нельзя —
          она и так 80% кадра, поэтому ужимаем содержимое. */}
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center',
        paddingTop: title ? height * 0.10 : 0,
        transform: `scale(${items.length >= 4 ? 0.68 : items.length === 3 ? 0.80 : 1})`}}>
        {kind === 'gauge' && <Gauge items={items as Item[]} width={width} />}
        {kind === 'split' && <Split items={items as Item[]} width={width} />}
        {kind === 'equation' && <Equation lines={items as string[]} width={width} />}
        {kind === 'counter' && <Counter lines={items as string[]} width={width} out={outline} />}
        {kind === 'cell' && <Cell labels={items as string[]} width={width} />}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Лёгкая зернистость бумаги, чтобы схема не выглядела стерильным вектором. */
const Grain: React.FC = () => (
  <AbsoluteFill style={{
    opacity: 0.07, mixBlendMode: 'multiply',
    backgroundImage:
      'radial-gradient(#8a7f70 1px, transparent 1px), radial-gradient(#8a7f70 1px, transparent 1px)',
    backgroundSize: '7px 7px, 11px 11px',
    backgroundPosition: '0 0, 4px 6px',
  }} />
);


/** Текст появляется как будто его пишут: шторка слева направо плюс лёгкий выезд. */
const Write: React.FC<{delay?: number; children: React.ReactNode}> = ({delay = 0, children}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: {damping: 200, stiffness: 90, mass: 0.9}});
  return (
    <div style={{
      clipPath: `inset(0 ${(1 - s) * 100}% 0 0)`,
      transform: `translateX(${(1 - s) * -18}px)`,
      willChange: 'clip-path, transform',
    }}>{children}</div>
  );
};

const Title: React.FC<{text: string; width: number}> = ({text, width}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const s = spring({frame, fps, config: cfgSpring});
  return (
    <div style={{position: 'absolute', top: '19%', width: '100%', textAlign: 'center',
      opacity: s, transform: `translateY(${(1 - s) * -16}px)`}}>
      <span style={{fontSize: K(height, 0.062), fontWeight: 800, color: C.ink,
        letterSpacing: 1}}>{text}</span>
    </div>
  );
};

const Gauge: React.FC<{items: Item[]; width: number}> = ({items, width}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const max = Math.max(...items.map((i) => i.max ?? i.value ?? 1), 1);
  const barW = width * 0.66;
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: height * 0.055}}>
      {items.map((it, i) => {
        const s = spring({frame: frame - i * 8, fps, config: cfgSpring});
        const frac = ((it.value ?? 0) / max) * s;
        return (
          <div key={i}>
            <div style={{fontSize: K(height, 0.040), color: C.ink, marginBottom: K(height, 0.014),
              fontWeight: 700, opacity: s}}>{it.label}</div>
            <div style={{width: barW, height: K(height, 0.095), border: `${K(height, 0.008)}px solid ${C.ink}`,
              borderRadius: 4, background: '#fff', position: 'relative', overflow: 'hidden'}}>
              <div style={{position: 'absolute', inset: 0, width: `${frac * 100}%`,
                background: i === 0 ? C.sea : C.accent}} />
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Split: React.FC<{items: Item[]; width: number}> = ({items, width}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const total = items.reduce((a, b) => a + (b.value ?? 0), 0) || 1;
  const barW = width * 0.66;
  const cols = [C.sea, C.accent, C.dim];
  return (
    <div>
      <div style={{width: barW, height: K(height, 0.14), border: `${K(height, 0.008)}px solid ${C.ink}`, borderRadius: 4,
        display: 'flex', overflow: 'hidden', background: '#fff'}}>
        {items.map((it, i) => {
          const s = spring({frame: frame - i * 10, fps, config: cfgSpring});
          return <div key={i} style={{width: `${((it.value ?? 0) / total) * 100 * s}%`,
            background: cols[i % cols.length], borderRight: i < items.length - 1 ? `${K(height, 0.008)}px solid ${C.ink}` : undefined}} />;
        })}
      </div>
      <div style={{display: 'flex', width: barW, marginTop: 14}}>
        {items.map((it, i) => (
          <div key={i} style={{width: `${((it.value ?? 0) / total) * 100}%`,
            fontSize: K(height, 0.036), color: C.ink, fontWeight: 700}}>{it.label}</div>
        ))}
      </div>
    </div>
  );
};

const Equation: React.FC<{lines: string[]; width: number}> = ({lines, width}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: height * 0.028}}>
      {lines.map((ln, i) => {
        const s = spring({frame: frame - i * 11, fps, config: cfgSpring});
        const last = i === lines.length - 1;
        return (
          <Write key={i} delay={i * 11}><div style={{fontSize: K(height, last ? 0.13 : 0.095),
            fontWeight: 800, color: last ? C.accent : C.ink, opacity: s,
            }}>{ln}</div></Write>
        );
      })}
    </div>
  );
};

const Counter: React.FC<{lines: string[]; width: number; out?: boolean}> = ({lines, width, out}) => {
  const frame = useCurrentFrame();
  const {fps, height} = useVideoConfig();
  const s = spring({frame, fps, config: cfgSpring});
  const [big, sub] = [lines[0] ?? '', lines[1] ?? ''];
  return (
    <div style={{textAlign: 'center', transform: `scale(${0.9 + 0.1 * s})`, opacity: s}}>
      <Write delay={2}><div style={{fontSize: K(height, 0.30), fontWeight: 800,
        color: out ? C.accent : C.ink, lineHeight: 1,
        WebkitTextStroke: out ? `${Math.round(height*0.010)}px ${C.ink}` : undefined,
        paintOrder: 'stroke fill',
        textShadow: out ? `0 ${Math.round(height*0.008)}px 0 ${C.ink}` : undefined}}>{big}</div></Write>
      <div style={{height: K(height, 0.010), width: width * 0.22 * s, background: C.accent, margin: '3% auto'}} />
      <div style={{fontSize: K(height, 0.050), color: out ? '#F2E9D8' : C.dim, fontWeight: 700,
        WebkitTextStroke: out ? `${Math.round(height*0.004)}px ${C.ink}` : undefined,
        paintOrder: 'stroke fill'}}>{sub}</div>
    </div>
  );
};

/** Клетка отдаёт воду наружу: круг сжимается, стрелки уходят от него. */
const Cell: React.FC<{labels: string[]; width: number}> = ({labels, width}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, height} = useVideoConfig();
  const p = interpolate(frame, [0, durationInFrames * 0.75], [0, 1],
    {extrapolateRight: 'clamp', easing: ease});
  const s = spring({frame, fps, config: cfgSpring});
  const R = height * 0.21;
  const r = R * (1 - 0.3 * p);
  return (
    <div style={{position: 'relative', width: R * 4, height: R * 3,
      display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
      <svg width={R * 4} height={R * 3} style={{position: 'absolute'}}>
        {[0, 45, 90, 135, 180, 225, 270, 315].map((deg, i) => {
          const a = (deg * Math.PI) / 180;
          const x0 = R * 2 + Math.cos(a) * (r + height * 0.022);
          const y0 = R * 1.5 + Math.sin(a) * (r + height * 0.022);
          const len = height * (0.05 + 0.06 * p);
          return (
            <line key={i} x1={x0} y1={y0}
              x2={x0 + Math.cos(a) * len} y2={y0 + Math.sin(a) * len}
              stroke={C.sea} strokeWidth={K(height, 0.010)} strokeLinecap="round" opacity={s} />
          );
        })}
        <circle cx={R * 2} cy={R * 1.5} r={r} fill={C.accent} stroke={C.ink} strokeWidth={K(height, 0.010)} />
      </svg>
      <div style={{position: 'absolute', bottom: 0, width: '100%', display: 'flex',
        justifyContent: 'space-between', fontSize: K(height, 0.038),
        color: C.ink, fontWeight: 700, opacity: s}}>
        <span>{labels[0]}</span><span>{labels[1]}</span>
      </div>
    </div>
  );
};
