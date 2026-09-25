import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig,
  Easing} from 'remotion';
import {loadFont} from '@remotion/google-fonts/CourierPrime';

// Весь текст ВНУТРИ роликов — Courier Prime Bold (channels.work.typography).
// Машинопись читается как документ, а документ и есть предмет канала.
// Гротеск остаётся только на обложках и баннере, Special Elite — на заставке.
const {fontFamily: MONO} = loadFont();

/** Инфографика Terms of Employment: фишка поверх кадра, не отдельный экран.
 *
 *  Правило канала (и общее правило проекта): числа и подписи рисует Remotion и
 *  кладёт ПОВЕРХ рисунка. Отдельные экраны со словами из дикторского текста —
 *  брак: зритель уже слышит эту фразу, читать её нечего.
 *
 *  Фишка сделана как кусок той же ризографской печати: сплошная плашка, тонкая
 *  светлая рамка внутри, смещение красного слоя на пару пикселей и зерно. */
const NAVY = '#1B2A5E';
const OCHRE = '#C89A3C';
const RED = '#E4533A';
const PAPER = '#F2ECE0';
const ease = Easing.bezier(0.33, 0, 0.2, 1);

export type WorkChipProps = {
  bg?: string;                       // кадр под фишкой (путь в public/)
  transparent?: boolean;             // рендер с альфой для сборки
  side?: 'left' | 'right';
  big: string;                       // главное число или слово
  small?: string;                    // короткая подпись под ним
  kicker?: string;                   // строка над числом
  /** сравнение: до четырёх полос, самая длинная — акцент */
  bars?: {label: string; value: number}[];
};

export const WorkChip: React.FC<WorkChipProps> = ({
  bg, transparent, side = 'left', big, small, kicker, bars,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width, height} = useVideoConfig();
  const IN = 14;
  const enter = spring({frame, fps, config: {damping: 200, stiffness: 120, mass: 0.7}});
  const exit = interpolate(frame, [durationInFrames - 10, durationInFrames], [1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.quad)});
  const a = enter * exit;
  const dy = (1 - enter) * 34;
  const pad = Math.round(width * 0.035);

  const card: React.CSSProperties = {
    position: 'absolute',
    [side]: Math.round(width * 0.07),
    bottom: Math.round(height * 0.12),
    background: NAVY,
    padding: `${pad * 0.8}px ${pad}px`,
    opacity: a,
    transform: `translateY(${dy}px)`,
    // светлая линия внутри — так печатают плашку в два прогона
    boxShadow: `inset 0 0 0 3px ${PAPER}22, 0 ${Math.round(height * 0.012)}px 0 ${RED}`,
    maxWidth: width * 0.44,
  };

  return (
    <AbsoluteFill style={{backgroundColor: transparent ? 'transparent' : PAPER}}>
      {bg && !transparent && (
        <Img src={staticFile(bg)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      )}
      <div style={card}>
        {kicker && (
          <div style={{
            font: `700 ${Math.round(height * 0.024)}px ${MONO}, monospace`,
            letterSpacing: 3, color: OCHRE, marginBottom: 10, textTransform: 'uppercase',
          }}>{kicker}</div>
        )}
        <div style={{position: 'relative'}}>
          {/* смещённый красный слой: печать в два прогона не совмещается идеально */}
          <div style={{
            position: 'absolute', left: 3, top: 2, color: RED, opacity: 0.55,
            font: `700 ${Math.round(height * 0.105)}px ${MONO}, monospace`,
            lineHeight: 0.96, whiteSpace: 'pre',
          }}>{big}</div>
          <div style={{
            color: PAPER, position: 'relative',
            font: `700 ${Math.round(height * 0.105)}px ${MONO}, monospace`,
            lineHeight: 0.96, whiteSpace: 'pre',
          }}>{big}</div>
        </div>
        {small && (
          <div style={{
            font: `700 ${Math.round(height * 0.028)}px ${MONO}, monospace`,
            color: PAPER, opacity: 0.88, marginTop: 8,
          }}>{small}</div>
        )}
        {bars && (
          <div style={{marginTop: pad * 0.6, display: 'grid', gap: 10}}>
            {bars.map((b, i) => {
              const max = Math.max(...bars.map((x) => x.value)) || 1;
              const w = interpolate(frame, [IN + i * 4, IN + i * 4 + 16], [0, b.value / max],
                {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
              const top = b.value === max;
              return (
                <div key={b.label} style={{display: 'flex', alignItems: 'center', gap: 14}}>
                  <div style={{
                    width: Math.round(width * 0.07), color: PAPER, opacity: 0.8,
                    font: `700 ${Math.round(height * 0.022)}px ${MONO}, monospace`,
                  }}>{b.label}</div>
                  <div style={{
                    height: Math.round(height * 0.035), width: `${w * 100}%`,
                    background: top ? RED : OCHRE, minWidth: 4,
                  }} />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
