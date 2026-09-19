import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig,
  Easing} from 'remotion';
import {HAND, INK, RUST, TYPE} from './NotebookIntro';

/** Инфографика Survivor's Notebook: клочок бумаги поверх рисунка.
 *
 *  Идея Евгения 2026-09-18: инфографика не отдельным экраном, а куском той же
 *  дневниковой бумаги — выезжает сбоку, закрывает часть кадра, рисунок под ним
 *  остаётся. Смерти — крестики-могилки в списке экипажа, без изображения смерти.
 *
 *  Все тексты и числа приходят из раскадровки, а она — из brief.json. */
const ease = Easing.bezier(0.33, 0, 0.2, 1);
const PENCIL = '#4E4944';

export type RosterData = {
  names: string[];
  dead?: string[];      // крестики, уже стоявшие раньше
  mark?: string[];      // крестики, которые ставим в этом кадре
  lost?: string[];      // пропавшие: знак вопроса
  count?: string;       // живых после кадра
  was?: string;         // прежнее число, зачёркивается
};
export type ScrapProps = {
  bg?: string;                 // рисунок под клочком (путь в public/)
  side?: 'left' | 'right';
  type: 'roster' | 'date' | 'letter' | 'compare' | 'image';
  /** картинка для type=image (карта), путь в public/ */
  src?: string;
  /** без фона: слой альфой поверх видео с наездом (сборка) */
  transparent?: boolean;
  roster?: RosterData;
  big?: string;
  small?: string;
  text?: string;
  items?: {label: string; value: string; unit: string}[];
  note?: string;
};

/** Рваный край: полигон с мелкими зубцами, детерминированный по seed. */
const torn = (seed: number) => {
  const pts: string[] = [];
  // два слоя шума: крупные надрывы и мелкие волокна
  const r = (i: number) => 0.6 * (Math.sin(seed * 91.7 + i * 12.3) * 0.5 + 0.5)
    + 0.4 * (Math.sin(seed * 13.1 + i * 57.9) * 0.5 + 0.5);
  const n = 60;
  for (let i = 0; i <= n; i++) pts.push(`${(i / n) * 100}% ${r(i) * 3.2}%`);
  for (let i = 0; i <= n; i++) pts.push(`${100 - r(i + 50) * 2.4}% ${(i / n) * 100}%`);
  for (let i = n; i >= 0; i--) pts.push(`${(i / n) * 100}% ${100 - r(i + 100) * 3.6}%`);
  for (let i = n; i >= 0; i--) pts.push(`${r(i + 150) * 2.2}% ${(i / n) * 100}%`);
  return `polygon(${pts.join(',')})`;
};

/** Карандашный крестик-могилка: вертикаль, потом перекладина. */
const Grave: React.FC<{p: number; s: number}> = ({p, s}) => {
  const v = Math.min(p * 2, 1), h = Math.max(p * 2 - 1, 0);
  return (
    <svg width={s} height={s * 1.3} style={{overflow: 'visible'}}>
      <line x1={s / 2} y1={s * 0.1} x2={s / 2} y2={s * 0.1 + s * 1.1 * v}
        stroke={PENCIL} strokeWidth={s * 0.11} strokeLinecap="round" />
      {h > 0 && <line x1={s / 2 - s * 0.36 * h} y1={s * 0.42} x2={s / 2 + s * 0.36 * h} y2={s * 0.42}
        stroke={PENCIL} strokeWidth={s * 0.11} strokeLinecap="round" />}
    </svg>
  );
};

const Roster: React.FC<{d: RosterData; t0: number; H: number}> = ({d, t0, H}) => {
  const frame = useCurrentFrame();
  const fs = H * 0.036;
  const dead = new Set(d.dead || []);
  const lost = new Set(d.lost || []);
  const mark = d.mark || [];
  const half = Math.ceil(d.names.length / 2);
  const cols = [d.names.slice(0, half), d.names.slice(half)];
  const cnt = interpolate(frame, [t0 + 10 + mark.length * 7, t0 + 22 + mark.length * 7], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  const nameRow = (n: string) => {
    const mi = mark.indexOf(n);
    const p = mi >= 0 ? interpolate(frame, [t0 + 6 + mi * 7, t0 + 14 + mi * 7], [0, 1],
      {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease}) : dead.has(n) ? 1 : 0;
    const gone = p > 0;
    return (
      <div key={n} style={{display: 'flex', alignItems: 'center', height: fs * 1.12}}>
        <div style={{width: fs * 1.0, display: 'flex', justifyContent: 'center'}}>
          {gone ? <Grave p={p} s={fs * 0.7} /> : lost.has(n)
            ? <span style={{fontFamily: HAND, fontSize: fs * 1.05, color: RUST}}>?</span> : null}
        </div>
        <span style={{fontFamily: HAND, fontSize: fs, color: INK,
          opacity: gone ? 0.45 + 0.55 * (1 - p) : 1}}>{n}</span>
      </div>
    );
  };
  return (
    <div>
      <div style={{fontFamily: TYPE, fontSize: fs * 0.62, color: '#5C514B', letterSpacing: '0.12em',
        marginBottom: fs * 0.4}}>ABOARD THE KARLUK</div>
      <div style={{display: 'flex', gap: fs * 1.2}}>
        {cols.map((c, i) => <div key={i}>{c.map(nameRow)}</div>)}
      </div>
      {d.count ? (
        <div style={{marginTop: fs * 0.5, display: 'flex', alignItems: 'baseline', gap: fs * 0.6}}>
          {d.was ? (
            <span style={{position: 'relative', fontFamily: HAND, fontSize: fs * 1.9, color: INK, opacity: 0.55}}>
              {d.was}
              <span style={{position: 'absolute', left: -fs * 0.1, top: '52%', height: fs * 0.12,
                width: `${cnt * 120}%`, background: RUST, transform: 'rotate(-8deg)'}} />
            </span>
          ) : null}
          <span style={{fontFamily: HAND, fontSize: fs * 2.2, color: INK, opacity: d.was ? cnt : 1}}>
            {d.count}</span>
          <span style={{fontFamily: HAND, fontSize: fs * 1.0, color: INK, opacity: d.was ? cnt : 1}}>alive</span>
        </div>
      ) : null}
    </div>
  );
};

export const Scrap: React.FC<ScrapProps> = (p) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps, durationInFrames} = useVideoConfig();
  const side = p.side || 'right';
  const inn = spring({frame: frame - 2, fps, config: {damping: 16, stiffness: 90, mass: 0.9}});
  const out = interpolate(frame, [durationInFrames - 8, durationInFrames], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  const land = 12;   // кадр, когда клочок улёгся — после него пишем карандашом
  const w = p.type === 'roster' ? W * 0.42 : p.type === 'image' ? W * 0.44 : W * 0.38;
  const dir = side === 'right' ? 1 : -1;
  const x = (1 - inn + out) * dir * (w + W * 0.1);
  const rot = dir * (2.2 + (1 - inn) * 6);

  const body = () => {
    if (p.type === 'roster' && p.roster) return <Roster d={p.roster} t0={land} H={H} />;
    if (p.type === 'image' && p.src) return (
      <div>
        <Img src={staticFile(p.src)} style={{width: '100%', display: 'block', opacity: 0.93,
          mixBlendMode: 'multiply'}} />
        {p.note ? <div style={{fontFamily: HAND, fontSize: H * 0.05, color: INK, marginTop: H * 0.012,
          textAlign: 'center'}}>{p.note}</div> : null}
      </div>
    );
    if (p.type === 'date') return (
      <div style={{textAlign: 'center', padding: `${H * 0.03}px 0`}}>
        <div style={{fontFamily: HAND, fontSize: H * 0.12, color: INK, lineHeight: 1}}>{p.big}</div>
        <div style={{fontFamily: TYPE, fontSize: H * 0.04, color: '#5C514B', marginTop: H * 0.02,
          letterSpacing: '0.1em'}}>{p.small}</div>
      </div>
    );
    if (p.type === 'letter') return (
      <div style={{fontFamily: HAND, fontSize: H * 0.045, color: INK, lineHeight: 1.35}}>
        “{p.text}…”
        <div style={{fontFamily: TYPE, fontSize: H * 0.026, color: '#5C514B', marginTop: H * 0.03}}>
          {p.note}</div>
      </div>
    );
    if (p.type === 'compare' && p.items) {
      const g = interpolate(frame, [land, land + 20], [0, 1],
        {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
      const hMax = H * 0.36;
      return (
        <div>
          <div style={{display: 'flex', alignItems: 'flex-end', gap: w * 0.1, height: hMax + H * 0.02,
            justifyContent: 'center'}}>
            {/* гребень: рваный треугольник из блоков */}
            <svg width={w * 0.34} height={hMax}>
              <path d={`M 0 ${hMax} L ${w * 0.07} ${hMax * (1 - 0.55 * g)} L ${w * 0.12} ${hMax * (1 - 0.7 * g)} `
                + `L ${w * 0.17} ${hMax * (1 - g)} L ${w * 0.23} ${hMax * (1 - 0.8 * g)} L ${w * 0.34} ${hMax} Z`}
                fill="rgba(160,190,205,0.35)" stroke={PENCIL} strokeWidth={3} strokeLinejoin="round" />
            </svg>
            {/* дом в десять этажей */}
            <svg width={w * 0.22} height={hMax}>
              <rect x={2} y={hMax * (1 - g)} width={w * 0.22 - 4} height={hMax * g}
                fill="none" stroke={PENCIL} strokeWidth={3} />
              {Array.from({length: 10}).map((_, i) => (
                <line key={i} x1={2} x2={w * 0.22 - 2} y1={hMax - (hMax / 10) * i} y2={hMax - (hMax / 10) * i}
                  stroke={PENCIL} strokeWidth={1.5} opacity={g > i / 10 ? 0.6 : 0} />
              ))}
            </svg>
          </div>
          <div style={{display: 'flex', justifyContent: 'center', gap: w * 0.12, marginTop: H * 0.01}}>
            {p.items.map((it) => (
              <div key={it.label} style={{textAlign: 'center', fontFamily: HAND, color: INK}}>
                <div style={{fontSize: H * 0.05}}>{it.value} {it.unit}</div>
                <div style={{fontSize: H * 0.033, opacity: 0.8}}>{it.label}</div>
              </div>
            ))}
          </div>
          {p.note ? <div style={{fontFamily: TYPE, fontSize: H * 0.024, color: '#5C514B', textAlign: 'center',
            marginTop: H * 0.015, letterSpacing: '0.1em'}}>{p.note}</div> : null}
        </div>
      );
    }
    return null;
  };

  return (
    <AbsoluteFill style={{backgroundColor: p.transparent ? 'transparent' : '#1A1612'}}>
      {p.transparent ? <AbsoluteFill style={{backgroundColor: `rgba(20,16,10,${0.12 * inn * (1 - out)})`}} /> : null}
      {p.bg && !p.transparent ? <Img src={staticFile(p.bg)} style={{width: W, height: H, objectFit: 'cover',
        filter: `brightness(${1 - 0.12 * inn * (1 - out)})`}} /> : null}
      <div style={{
        position: 'absolute', top: H * 0.08, [side]: W * 0.05, width: w,
        transform: `translateX(${x}px) rotate(${rot}deg)`,
        filter: 'drop-shadow(6px 10px 14px rgba(0,0,0,0.35))',
      }}>
        <div style={{
          clipPath: torn(p.type.length + (side === 'right' ? 3 : 7)),
          backgroundImage: `url(${staticFile('survival/page_blank.jpg')})`,
          backgroundSize: `${W}px ${H}px`, backgroundPosition: `-${W * 0.3}px -${H * 0.15}px`,
          padding: `${H * 0.05}px ${W * 0.03}px ${H * 0.045}px ${W * 0.035}px`,
        }}>{body()}</div>
        {/* полоска скотча сверху */}
        <div style={{position: 'absolute', top: -H * 0.018, left: '38%', width: W * 0.08, height: H * 0.04,
          background: 'rgba(222,208,170,0.65)', transform: 'rotate(-4deg)',
          boxShadow: '0 1px 2px rgba(0,0,0,0.12)'}} />
      </div>
    </AbsoluteFill>
  );
};
