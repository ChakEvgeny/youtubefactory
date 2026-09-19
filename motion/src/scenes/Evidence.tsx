import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig,
  Easing} from 'remotion';
import {INK, YEL, STEEL} from './Noir';

/** Инфографика The Case Room: карточка из дела поверх панели.
 *
 *  Аналог клочка блокнота (Scrap) у Survivor's Notebook: не отдельный экран, а
 *  предмет — машинописная карточка со скрепкой, выезжает сбоку, закрывает часть
 *  кадра, панель под ней гаснет. Жёлтый — маркер по главному числу.
 *  Все тексты и числа — из раскадровки, та — из brief.json. */
const CARD = '#F2EAD6';
const ANTON = 'Anton, Impact, sans-serif';
const TYPE = '"Special Elite", monospace';
const ease = Easing.bezier(0.33, 0, 0.2, 1);

export type EvidenceProps = {
  type: 'letter' | 'flow' | 'tank' | 'tally' | 'bars' | 'counter' | 'date';
  bg?: string; transparent?: boolean; side?: 'left' | 'right';
  text?: string; note?: string; big?: string; small?: string;
  items?: (string | {label: string; value: number; unit?: string})[];
  water_ft?: number; oil_ft?: number;
};

/** Маркер: жёлтая полоса под текстом, наносится слева направо. */
const Mark: React.FC<{p: number; children: React.ReactNode}> = ({p, children}) => (
  <span style={{backgroundImage: `linear-gradient(${YEL}, ${YEL})`, backgroundRepeat: 'no-repeat',
    backgroundSize: `${p * 100}% 42%`, backgroundPosition: '0 88%', padding: '0 0.08em'}}>{children}</span>
);

export const Evidence: React.FC<EvidenceProps> = (p) => {
  const frame = useCurrentFrame();
  const {width: W, height: H, fps, durationInFrames} = useVideoConfig();
  const side = p.side || 'right';
  const inn = spring({frame: frame - 2, fps, config: {damping: 17, stiffness: 95, mass: 0.9}});
  const out = interpolate(frame, [durationInFrames - 8, durationInFrames], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  const land = 12;
  const g = interpolate(frame, [land, land + 22], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  const w = ['tank', 'tally', 'bars', 'flow'].includes(p.type) ? W * 0.44 : W * 0.4;
  const dir = side === 'right' ? 1 : -1;
  const x = (1 - inn + out) * dir * (w + W * 0.1);
  const rot = dir * (1.6 + (1 - inn) * 5);
  const fs = H * 0.036;

  const body = () => {
    switch (p.type) {
      case 'letter': return (
        <div>
          <div style={{fontFamily: TYPE, fontSize: fs * 0.7, letterSpacing: '0.14em', color: STEEL, marginBottom: fs * 0.6}}>
            {p.note}</div>
          <div style={{fontFamily: TYPE, fontSize: fs * 1.05, color: INK, lineHeight: 1.45}}>“<Mark p={g}>{p.text}</Mark>”</div>
        </div>);
      case 'counter': return (
        <div style={{textAlign: 'center', padding: `${H * 0.02}px 0`}}>
          {/* кегль от длины: «$13,560,000» в фиксированном размере вылезал за карточку */}
          <div style={{fontFamily: ANTON, fontSize: Math.min(H * 0.15, (w * 0.82) / (0.5 * Math.max((p.big || '').length, 1))),
            color: INK, lineHeight: 1, whiteSpace: 'nowrap'}}><Mark p={g}>{p.big}</Mark></div>
          <div style={{fontFamily: TYPE, fontSize: fs * 0.95, color: INK, marginTop: H * 0.025}}>{p.small}</div>
        </div>);
      case 'date': return (
        <div style={{textAlign: 'center', padding: `${H * 0.02}px 0`}}>
          <div style={{fontFamily: ANTON, fontSize: H * 0.11, color: INK, lineHeight: 1}}>{p.big}</div>
          <div style={{fontFamily: TYPE, fontSize: fs * 0.95, color: INK, marginTop: H * 0.025}}><Mark p={g}>{p.small}</Mark></div>
        </div>);
      case 'flow': {
        const it = (p.items || []) as string[];
        return (
          <div>
            <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              {it.map((s, i) => {
                const q = interpolate(frame, [land + i * 6, land + i * 6 + 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
                return (
                  <React.Fragment key={s}>
                    {i ? <div style={{fontFamily: ANTON, fontSize: fs * 1.4, color: INK, opacity: q}}>→</div> : null}
                    <div style={{opacity: q, border: `3px solid ${INK}`, padding: `${fs * 0.35}px ${fs * 0.45}px`,
                      fontFamily: ANTON, fontSize: fs * 1.05, color: INK, background: i === 1 ? YEL : 'transparent'}}>{s}</div>
                  </React.Fragment>);
              })}
            </div>
            {p.note ? <div style={{fontFamily: TYPE, fontSize: fs * 0.85, color: INK, marginTop: fs * 1.1, textAlign: 'center'}}>{p.note}</div> : null}
          </div>);
      }
      case 'tank': {
        // разрез цистерны: высота воды и масла в масштабе, трубка под люком заполнена маслом
        const tw = w * 0.42, th = H * 0.46, total = (p.water_ft || 40) + (p.oil_ft || 2);
        const oilH = th * (p.oil_ft || 2) / total, waterH = (th - oilH) * g;
        return (
          <div style={{display: 'flex', alignItems: 'flex-end', gap: w * 0.06}}>
            <svg width={tw} height={th + 30} style={{overflow: 'visible'}}>
              <rect x={2} y={30} width={tw - 4} height={th} fill="none" stroke={INK} strokeWidth={5} />
              <rect x={5} y={30 + th - waterH} width={tw - 10} height={waterH} fill={STEEL} opacity={0.55} />
              <rect x={5} y={30 + th - waterH - oilH * g} width={tw - 10} height={oilH * g} fill={YEL} />
              <rect x={tw * 0.44} y={10} width={tw * 0.12} height={20} fill="none" stroke={INK} strokeWidth={4} />
              <rect x={tw * 0.47} y={30} width={tw * 0.06} height={th * g} fill={YEL} stroke={INK} strokeWidth={3} />
            </svg>
            <div style={{fontFamily: TYPE, fontSize: fs * 0.9, color: INK, lineHeight: 1.5}}>
              <div><Mark p={g}>{p.oil_ft} ft of oil</Mark></div>
              <div>{p.water_ft} ft of seawater</div>
              <div style={{marginTop: fs * 0.8}}>{p.note}</div>
            </div>
          </div>);
      }
      case 'tally': {
        // сетка значков-цистерн: каждый класс своим видом, «несуществующая» — пунктир
        const it = (p.items || []) as {label: string; value: number}[];
        const kinds = [{fill: STEEL, dash: ''}, {fill: '#B8AE9C', dash: ''}, {fill: 'none', dash: '4 4'}, {fill: YEL, dash: ''}];
        let n = 0;
        const icons: React.ReactNode[] = [];
        it.forEach((c, k) => { for (let i = 0; i < c.value; i++) {
          const q = interpolate(frame, [land + n * 0.7, land + n * 0.7 + 4], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          icons.push(<svg key={n} width={fs * 1.25} height={fs * 1.6} style={{opacity: q}}>
            <rect x={2} y={4} width={fs * 1.25 - 4} height={fs * 1.6 - 6} rx={4} fill={kinds[k].fill}
              stroke={INK} strokeWidth={2.5} strokeDasharray={kinds[k].dash} /></svg>); n++; } });
        return (
          <div>
            <div style={{display: 'flex', flexWrap: 'wrap', gap: fs * 0.2, width: w * 0.86}}>{icons}</div>
            <div style={{fontFamily: TYPE, fontSize: fs * 0.8, color: INK, marginTop: fs * 0.7, lineHeight: 1.55}}>
              {it.map((c, k) => <div key={k}><span style={{display: 'inline-block', width: fs * 0.7, height: fs * 0.7,
                background: kinds[k].fill === 'none' ? 'transparent' : kinds[k].fill, border: `2px ${kinds[k].dash ? 'dashed' : 'solid'} ${INK}`,
                marginRight: fs * 0.4, verticalAlign: 'middle'}} />{c.value} {c.label}</div>)}
            </div>
          </div>);
      }
      case 'bars': {
        const it = (p.items || []) as {label: string; value: number; unit?: string}[];
        const mx = Math.max(...it.map((c) => c.value));
        return (
          <div>
            {it.map((c, k) => (
              <div key={k} style={{marginBottom: fs * 0.9}}>
                <div style={{fontFamily: TYPE, fontSize: fs * 0.85, color: INK}}>{c.label}</div>
                <div style={{display: 'flex', alignItems: 'center', gap: fs * 0.5}}>
                  <div style={{height: fs * 1.3, width: Math.max(w * 0.5 * (c.value / mx) * g, 4),
                    background: k ? YEL : STEEL, border: `3px solid ${INK}`}} />
                  <div style={{fontFamily: ANTON, fontSize: fs * 1.2, color: INK, whiteSpace: 'nowrap'}}>{c.value.toLocaleString('en-US')} {c.unit}</div>
                </div>
              </div>))}
            {p.note ? <div style={{fontFamily: TYPE, fontSize: fs * 0.7, color: STEEL, letterSpacing: '0.12em'}}>{p.note}</div> : null}
          </div>);
      }
    }
    return null;
  };

  return (
    <AbsoluteFill style={{backgroundColor: p.transparent ? 'transparent' : INK}}>
      {p.bg && !p.transparent ? <Img src={staticFile(p.bg)} style={{width: W, height: H, objectFit: 'cover'}} /> : null}
      <AbsoluteFill style={{backgroundColor: `rgba(10,9,8,${0.35 * inn * (1 - out)})`}} />
      <div style={{position: 'absolute', top: H * 0.1, [side]: W * 0.05, width: w,
        transform: `translateX(${x}px) rotate(${rot}deg)`, filter: 'drop-shadow(8px 12px 16px rgba(0,0,0,0.5))'}}>
        <div style={{background: CARD, border: `3px solid ${INK}`, padding: `${H * 0.055}px ${W * 0.03}px ${H * 0.05}px`,
          backgroundImage: 'radial-gradient(rgba(90,80,60,0.12) 1px, transparent 1px)', backgroundSize: '6px 6px'}}>
          {body()}
        </div>
        {/* скрепка */}
        <svg width={W * 0.025} height={H * 0.09} style={{position: 'absolute', top: -H * 0.035, left: '12%'}}>
          <path d={`M ${W * 0.006} ${H * 0.08} V ${H * 0.012} a ${W * 0.0065} ${W * 0.0065} 0 0 1 ${W * 0.013} 0 V ${H * 0.07} a ${W * 0.004} ${W * 0.004} 0 0 1 -${W * 0.008} 0 V ${H * 0.025}`}
            fill="none" stroke="#8A8F94" strokeWidth={4} strokeLinecap="round" />
        </svg>
      </div>
    </AbsoluteFill>
  );
};
