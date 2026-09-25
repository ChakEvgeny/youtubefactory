import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';
import {loadFont} from '@remotion/google-fonts/CourierPrime';

/** Карточки канала Terms of Employment: всё, где есть число или список.
 *
 *  Нейросеть числа рисовать не умеет, а на слух они не держатся — поэтому
 *  таблицы, шкалы и таймлайны рисует код и кладёт ПОВЕРХ бумаги, а не вместо
 *  кадра. Шрифт тот же, что и во всём ролике: машинопись читается как документ.
 */
const {fontFamily: MONO} = loadFont();
const NAVY = '#1B2A5E';
const OCHRE = '#C89A3C';
const RED = '#E4533A';
const PAPER = '#F2ECE0';
const ease = Easing.bezier(0.33, 0, 0.2, 1);

export type WorkCardProps = {
  kind: 'typed' | 'scale' | 'timeline' | 'ladders' | 'bars' | 'table';
  lines?: string[];
  items?: any[];
  rows?: string[][];
  label?: string;
  seconds?: number;
  /** секунды от начала карточки, когда произносится каждая строка или столбик.
   *  Берутся из посимвольного выравнивания ElevenLabs при сборке: без них
   *  карточка висит статикой, и зритель двадцать секунд смотрит на таблицу. */
  beats?: number[];
  /** сколько первых строк уже стоят на листе, когда карточка появляется */
  shown?: number;
  /** карточка ложится ПОВЕРХ кадра раскрытой папкой, а не занимает экран целиком */
  overlay?: boolean;
  side?: 'left' | 'right';
};

const grain = (w: number, h: number): React.CSSProperties => ({
  position: 'absolute', inset: 0, pointerEvents: 'none', opacity: 0.16,
  backgroundImage:
    `radial-gradient(${NAVY} 0.5px, transparent 0.5px)`,
  backgroundSize: '3px 3px',
});

export const WorkCard: React.FC<WorkCardProps> = ({
  kind, lines = [], items = [], rows = [], label, beats, shown = 0,
  overlay = false, side = 'left',
}) => {
  const frame = useCurrentFrame();
  const {fps, width, height, durationInFrames} = useVideoConfig();
  const S = height / 1080;
  const out = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  /** кадр, на котором строка i должна появиться: по голосу, если он известен,
   *  иначе ровной лесенкой — но ровная лесенка это запасной вариант, не норма */
  const at = (i: number, fallback: number) =>
    beats && beats[i] !== undefined ? Math.round(beats[i] * fps) : i * fallback;

  const base: React.CSSProperties = {
    fontFamily: MONO, color: NAVY, background: PAPER, opacity: out,
    // содержимое по центру кадра: иначе всё висит в левом верхнем углу,
    // а нижние две трети экрана пустуют
    justifyContent: 'center', alignItems: 'center',
  };

  /** посимвольный набор: приём канала, 2–4 раза за ролик */
  const typed = () => {
    const per = Math.max(1, Math.floor((durationInFrames * 0.72) /
      Math.max(1, lines.join('').length)));   // набор занимает ~70% карточки
    const pre = lines.slice(0, shown).join('').length;
    const total = lines.join('').length;
    let left = Math.min(pre + Math.floor(frame / per), total);
    return (
      <div style={{display: 'grid', gap: 26 * S, padding: 90 * S}}>
        {lines.map((l, i) => {
          const take = Math.max(0, Math.min(l.length, left));
          left -= l.length;
          const caret = take > 0 && take < l.length;
          return (
            <div key={i} style={{font: `700 ${Math.round(78 * S)}px ${MONO}`, letterSpacing: 2}}>
              {l.slice(0, take)}
              {caret && <span style={{color: RED}}>_</span>}
            </div>
          );
        })}
      </div>
    );
  };

  /** шкала 6 → 12 → 18: значения появляются по очереди, последнее красное */
  const scale = () => (
    <div style={{display: 'flex', alignItems: 'center', gap: 40 * S, padding: 90 * S}}>
      {items.map((v: string, i: number) => {
        const a = spring({frame: frame - at(i, 9), fps, config: {damping: 200}});
        const last = i === items.length - 1;
        return (
          <React.Fragment key={v}>
            {i > 0 && <div style={{width: 70 * S, height: 6 * S, background: NAVY, opacity: a}} />}
            <div style={{
              font: `700 ${Math.round(150 * S)}px ${MONO}`, opacity: a,
              transform: `translateY(${(1 - a) * 26}px)`, color: last ? RED : NAVY,
            }}>{v}</div>
          </React.Fragment>
        );
      })}
      {label && <div style={{font: `700 ${Math.round(34 * S)}px ${MONO}`, opacity: out * 0.8,
        marginLeft: 30 * S, maxWidth: 360 * S}}>{label}</div>}
    </div>
  );

  /** таймлайн дат: по линии ползёт красная черта */
  const timeline = () => {
    // ширина берётся от КОНТЕЙНЕРА, а не от кадра: накладкой карточка живёт
    // внутри папки шириной чуть больше половины экрана, и линия, посчитанная
    // от 1920, уезжала за лист вместе с последней датой
    const p = interpolate(frame, [12, durationInFrames - 20], [0, 1],
      {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
    const n = Math.max(1, items.length - 1);
    return (
      <div style={{padding: `${140 * S}px ${110 * S}px`, width: '100%',
        boxSizing: 'border-box'}}>
        {label && <div style={{font: `700 ${Math.round(34 * S)}px ${MONO}`, marginBottom: 40 * S,
          letterSpacing: 3, textTransform: 'uppercase', color: OCHRE}}>{label}</div>}
        <div style={{position: 'relative', height: 8 * S, background: NAVY, width: '100%'}}>
          <div style={{position: 'absolute', left: 0, top: 0, height: '100%',
            width: `${p * 100}%`, background: RED}} />
          {items.map((v: string, i: number) => {
            // крайние подписи прижимаем к концам линии, средние центрируем:
            // иначе первая и последняя свисают за лист половиной своей ширины
            const edge = i === 0 ? 'flex-start' : i === items.length - 1 ? 'flex-end' : 'center';
            return (
              <div key={v} style={{
                position: 'absolute', left: `${(i / n) * 100}%`, top: -14 * S,
                display: 'flex', flexDirection: 'column', alignItems: edge,
                transform: edge === 'center' ? 'translateX(-50%)'
                  : edge === 'flex-end' ? 'translateX(-100%)' : 'none',
              }}>
                <div style={{width: 8 * S, height: 36 * S, background: NAVY,
                  alignSelf: edge === 'flex-end' ? 'flex-end' : 'flex-start'}} />
                <div style={{font: `700 ${Math.round(56 * S)}px ${MONO}`, marginTop: 24 * S,
                  whiteSpace: 'nowrap'}}>{v}</div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  /** две лесенки недель, обе упираются в один потолок */
  const ladders = () => {
    const maxSteps = Math.max(...items.map((x: any) => x.steps));
    return (
      <div style={{display: 'flex', gap: 120 * S, padding: 90 * S, alignItems: 'flex-end'}}>
        {items.map((lad: any, li: number) => (
          <div key={lad.label}>
            <div style={{display: 'flex', alignItems: 'flex-end', gap: 10 * S}}>
              {Array.from({length: lad.steps}).map((_, i) => {
                const a = spring({frame: frame - (at(li, 10) + i * 5), fps, config: {damping: 200}});
                return <div key={i} style={{
                  width: 54 * S, height: (60 + i * 52) * S * a,
                  background: i === lad.steps - 1 ? RED : OCHRE,
                }} />;
              })}
            </div>
            <div style={{height: 8 * S, background: NAVY, marginTop: 14 * S}} />
            <div style={{font: `700 ${Math.round(40 * S)}px ${MONO}`, marginTop: 16 * S}}>{lad.label}</div>
          </div>
        ))}
        {label && <div style={{font: `700 ${Math.round(34 * S)}px ${MONO}`, opacity: 0.8,
          alignSelf: 'flex-start'}}>{label}</div>}
      </div>
    );
  };

  /** два столбика в одном масштабе — чтобы разрыв был виден, а не назван */
  const bars = () => {
    const max = Math.max(...items.map((b: any) => b.value));
    return (
      <div style={{display: 'grid', gap: 54 * S, padding: 110 * S, width: '100%'}}>
        {items.map((b: any, i: number) => {
          const b0 = at(i, 12) + 10;
          const w = interpolate(frame, [b0, b0 + 30], [0, b.value / max],
            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
          const top = b.value === max;
          return (
            <div key={b.label}>
              <div style={{font: `700 ${Math.round(38 * S)}px ${MONO}`, marginBottom: 12 * S}}>
                {b.label}
              </div>
              <div style={{display: 'flex', alignItems: 'center', gap: 22 * S}}>
                <div style={{height: 64 * S, width: `${Math.max(w * 74, w > 0 ? 3 : 0)}%`,
                  background: top ? RED : OCHRE, minWidth: w > 0 ? 40 * S : 0}} />
                <div style={{font: `700 ${Math.round(64 * S)}px ${MONO}`}}>
                  {b.value}{b.unit ? ` ${b.unit}` : ''}</div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  /** таблица: строки появляются сверху вниз, помеченная — красным */
  const table = () => (
    <div style={{padding: 110 * S, display: 'grid', gap: 22 * S, width: '100%'}}>
      {rows.map((r, i) => {
        const a = spring({frame: frame - at(i, 8), fps, config: {damping: 200}});
        const accent = r[1] === '';
        return (
          <div key={i} style={{
            display: 'flex', justifyContent: 'space-between', opacity: a,
            transform: `translateY(${(1 - a) * 22}px)`,
            font: `700 ${Math.round(58 * S)}px ${MONO}`,
            color: accent ? RED : NAVY,
            borderBottom: `${3 * S}px solid ${accent ? RED : NAVY}22`, paddingBottom: 14 * S,
          }}>
            <div>{r[0]}</div><div>{r[1]}</div>
          </div>
        );
      })}
    </div>
  );

  const body = {typed, scale, timeline, ladders, bars, table}[kind];

  if (overlay) {
    // Инфографика — предмет поверх кадра, а не отдельный экран: раскрытая папка
    // въезжает с края, внутри неё строки и числа. Кадр под ней продолжает жить.
    const inSpr = spring({frame, fps, config: {damping: 200, stiffness: 90, mass: 0.9}});
    const dx = (1 - inSpr) * (side === 'left' ? -width * 0.5 : width * 0.5);
    const W = Math.round(width * 0.56);
    const Hh = Math.round(height * 0.62);
    const tab = Math.round(Hh * 0.10);
    return (
      <AbsoluteFill style={{background: 'transparent', opacity: out}}>
        <div style={{
          position: 'absolute', bottom: Math.round(height * 0.09),
          [side]: Math.round(width * 0.05), width: W, height: Hh,
          transform: `translateX(${dx}px) rotate(${side === 'left' ? -1.2 : 1.2}deg)`,
        }}>
          {/* язычок папки */}
          <div style={{
            position: 'absolute', top: -tab + 2, left: Math.round(W * 0.06),
            width: Math.round(W * 0.30), height: tab, background: OCHRE,
            borderTopLeftRadius: 10, borderTopRightRadius: 22,
            border: `${Math.max(3, Hh * 0.006)}px solid ${NAVY}`, borderBottom: 'none',
          }} />
          {/* корпус папки */}
          <div style={{
            position: 'absolute', inset: 0, background: OCHRE,
            border: `${Math.max(3, Hh * 0.006)}px solid ${NAVY}`,
            boxShadow: `${side === 'left' ? 14 : -14}px 16px 0 rgba(27,42,94,0.22)`,
          }} />
          {/* лист внутри папки */}
          <div style={{
            position: 'absolute', inset: `${Hh * 0.08}px ${W * 0.05}px ${Hh * 0.06}px`,
            background: PAPER, border: `2px solid ${NAVY}33`,
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            overflow: 'hidden', fontFamily: MONO, color: NAVY,
            padding: `${Hh * 0.05}px 0 0`,
          }}>
            <div style={{width: '100%', transform: 'scale(0.78)', transformOrigin: 'top center'}}>
              {body ? body() : null}
            </div>
          </div>
        </div>
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={base}>
      {body ? body() : null}
      <div style={grain(width, height)} />
    </AbsoluteFill>
  );
};
