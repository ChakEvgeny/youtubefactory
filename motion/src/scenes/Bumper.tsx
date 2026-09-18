import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing} from 'remotion';

/** Заставка канала: имя выводится невидимым карандашом.
 *
 *  Идея Евгения 2026-09-17: после вступления в ролике есть пауза — туда ставим
 *  заставку. Карандаша в кадре нет, видно только след: буквы проявляются слева
 *  направо, как будто их пишут. Звук карандаша накладывается отдельно и звучит
 *  ровно столько, сколько идёт письмо (`writeWindow` в консоли сборки).
 *
 *  Слова выводятся по очереди, а не строка целиком: одна общая шторка читается
 *  как выезд плашки, а не как письмо. */
const C = {paper: '#F2E9D8', ink: '#141210', accent: '#E2503C', sea: '#0E86C4'};
const K = (h: number, f: number) => Math.round(h * f);
const ease = Easing.bezier(0.33, 0, 0.2, 1);

export type BumperProps = {
  font?: string;
  words?: string[];
  /** кадров на слово; общий хвост после письма — остаток длительности */
  hold?: number;
};

/** Одно слово: шторка слева направо. Скорость неравномерная — рука не машина. */
const Word: React.FC<{text: string; from: number; span: number; size: number; color: string}> =
  ({text, from, span, size, color}) => {
    const frame = useCurrentFrame();
    const p = interpolate(frame, [from, from + span], [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease,
    });
    return (
      <span style={{
        display: 'inline-block',
        clipPath: `inset(0 ${(1 - p) * 100}% -18% 0)`,
        fontSize: size, fontWeight: 700, color, lineHeight: 1.15,
        willChange: 'clip-path',
      }}>{text}</span>
    );
  };

export const Bumper: React.FC<BumperProps> = ({font, words, hold = 26}) => {
  const frame = useCurrentFrame();
  const {height, width, fps, durationInFrames} = useVideoConfig();
  const w = words && words.length ? words : ['Why', '&', 'How'];

  const start = Math.round(fps * 0.35);          // короткий вдох перед первым штрихом
  const spans = w.map((t) => Math.max(Math.round(hold * Math.min(t.length, 4) / 3), 8));
  const froms: number[] = [];
  let acc = start;
  for (const s of spans) { froms.push(acc); acc += Math.round(s * 0.88); }
  const writeEnd = acc;

  // Подчёркивание коралловым — последний штрих, уже после слов.
  const line = interpolate(frame, [writeEnd + 4, writeEnd + Math.round(fps * 0.45)], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  // Общее затухание в самом конце, чтобы стык с роликом не был резким.
  const out = interpolate(frame, [durationInFrames - Math.round(fps * 0.35), durationInFrames],
    [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  const size = K(height, 0.185);

  return (
    <AbsoluteFill style={{backgroundColor: C.paper, fontFamily: font || 'Sriracha', opacity: out}}>
      <Grain />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', flexDirection: 'column'}}>
        <div style={{display: 'flex', alignItems: 'baseline', gap: K(height, 0.035)}}>
          {w.map((t, i) => (
            <Word key={i} text={t} from={froms[i]} span={spans[i]} size={size}
                  color={t === '&' ? C.accent : C.ink} />
          ))}
        </div>
        <div style={{
          marginTop: K(height, 0.03),
          width: width * 0.42 * line, height: K(height, 0.012),
          background: C.accent, borderRadius: K(height, 0.006),
        }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Grain: React.FC = () => (
  <AbsoluteFill style={{
    opacity: 0.07, mixBlendMode: 'multiply',
    backgroundImage:
      'radial-gradient(#8a7f70 1px, transparent 1px), radial-gradient(#8a7f70 1px, transparent 1px)',
    backgroundSize: '7px 7px, 11px 11px',
    backgroundPosition: '0 0, 4px 6px',
  }} />
);
