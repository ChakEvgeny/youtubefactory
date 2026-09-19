import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, interpolate, staticFile, useCurrentFrame,
  useVideoConfig, Easing} from 'remotion';
import {FLIP, HAND, INK, Leaf, RUST, Shade} from './NotebookIntro';

/** Аутро канала Survivor's Notebook.
 *
 *  Задумка Евгения 2026-09-18: последний кадр ролика перелистывается тем же
 *  движением, что в интро, открывается страница с «The End» тем же почерком.
 *  Под ним карандашные рамки с полосками скотча — места под элементы конечной
 *  заставки YouTube (две плитки видео и кружок подписки). Координаты рамок
 *  совпадают с SLOTS ниже: по ним ставить элементы в Studio.
 *
 *  Шаблон, а не файл: последний кадр подставляет сборщик ролика
 *  (`last` — путь внутри public/, копировать туда перед рендером). */
const ease = Easing.bezier(0.33, 0, 0.2, 1);
const PENCIL = '#5A5550';

/** Места под конечную заставку, в долях кадра: x, y, ширина, высота. */
export const SLOTS = {
  video1: [0.13, 0.41, 0.33, 0.33],
  video2: [0.54, 0.41, 0.33, 0.33],
  subscribe: [0.5, 0.87, 0.075], // центр x, центр y, радиус
};

export type NotebookOutroProps = {
  last?: string;
  /** масштаб последнего кадра, если в ролике на нём был наезд камеры */
  zoom?: number;
  end?: string;
  seconds?: number;
  /** рамки под плитки конечной заставки. Решение Евгения 2026-09-18: пока своих
   *  видео мало — без них, только «The End» по центру. */
  slots?: boolean;
};

/** Неровная карандашная рамка, прорисовывается по периметру. */
const Sketch: React.FC<{x: number; y: number; w: number; h: number; p: number; seed: number}> =
  ({x, y, w, h, p, seed}) => {
    const j = (i: number) => Math.sin(seed * 12.9 + i * 78.2) * 3;
    const d = `M ${x + j(1)} ${y + j(2)} L ${x + w + j(3)} ${y + j(4)} L ${x + w + j(5)} ${y + h + j(6)} `
      + `L ${x + j(7)} ${y + h + j(8)} Z`;
    const len = 2 * (w + h) + 40;
    return <path d={d} fill="none" stroke={PENCIL} strokeWidth={3} strokeLinejoin="round"
      strokeDasharray={len} strokeDashoffset={len * (1 - p)} opacity={0.75} />;
  };

const Tape: React.FC<{x: number; y: number; rot: number; o: number}> = ({x, y, rot, o}) => (
  <div style={{
    position: 'absolute', left: x - 55, top: y - 18, width: 110, height: 36,
    background: 'rgba(222, 208, 170, 0.62)', transform: `rotate(${rot}deg)`,
    boxShadow: '0 1px 2px rgba(0,0,0,0.12)', opacity: o,
  }} />
);

export const NotebookOutro: React.FC<NotebookOutroProps> = ({last, zoom = 1, end, slots = false}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const start = 6;
  const after = start + FLIP;

  const draw = interpolate(frame, [after + 6, after + 30], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
  const tape = interpolate(frame, [after + 26, after + 36], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  const [v1x, v1y, vw, vh] = SLOTS.video1.map((v, i) => v * (i % 2 ? height : width));
  const [v2x] = [SLOTS.video2[0] * width];
  const [sx, sy, sr] = [SLOTS.subscribe[0] * width, SLOTS.subscribe[1] * height, SLOTS.subscribe[2] * height];
  // плитки YouTube 16:9 — высоту рамки считаем от ширины, а не из SLOTS
  const tileH = vw * 9 / 16;

  return (
    <AbsoluteFill style={{backgroundColor: '#1A1612'}}>
      <AbsoluteFill>
        <Img src={staticFile('survival/page_blank.jpg')} style={{width, height, objectFit: 'cover'}} />
        <AbsoluteFill style={{alignItems: 'center', transform: 'rotate(-1deg)',
          ...(slots ? {paddingTop: height * 0.07} : {justifyContent: 'center'})}}>
          <div style={{fontFamily: HAND, fontSize: height * (slots ? 0.2 : 0.26), color: INK, opacity: 0.92, lineHeight: 1}}>
            {end || 'The End'}
          </div>
          <svg width={width * 0.3} height={height * 0.035}>
            <path d={`M ${width * 0.01} ${height * 0.01} Q ${width * 0.15} ${height * 0.028} ${width * 0.29} ${height * 0.013}`}
              stroke={RUST} strokeWidth={height * 0.006} fill="none" strokeLinecap="round" opacity={0.9} />
          </svg>
        </AbsoluteFill>
        {slots ? (<>
        <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
          <Sketch x={v1x} y={v1y} w={vw} h={tileH} p={draw} seed={1} />
          <Sketch x={v2x} y={v1y} w={vw} h={tileH} p={draw} seed={2} />
          <circle cx={sx} cy={sy} r={sr} fill="none" stroke={PENCIL} strokeWidth={3} opacity={0.75}
            strokeDasharray={2 * Math.PI * sr} strokeDashoffset={2 * Math.PI * sr * (1 - draw)} />
        </svg>
        <Tape x={v1x + 8} y={v1y + 4} rot={-24} o={tape} />
        <Tape x={v1x + vw - 8} y={v1y + tileH - 4} rot={-24} o={tape} />
        <Tape x={v2x + vw - 8} y={v1y + 4} rot={22} o={tape} />
        <Tape x={v2x + 8} y={v1y + tileH - 4} rot={22} o={tape} />
        </>) : null}
      </AbsoluteFill>
      {last ? (
        <>
          <Shade start={start} />
          <Leaf page={{img: last, note: '', zoom}} start={start} />
          <Sequence from={start - 1}><Audio src={staticFile('survival/flip_b1.mp3')} /></Sequence>
        </>
      ) : null}
    </AbsoluteFill>
  );
};
