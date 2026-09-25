import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, interpolate, staticFile, useCurrentFrame,
  useVideoConfig, Easing} from 'remotion';

/** Интро канала Survivor's Notebook.
 *
 *  Задумка Евгения 2026-09-18: листаются страницы полевого дневника с рисунками
 *  и записями, останавливаемся на титульной, камера наезжает на название,
 *  подзаголовок проявляется вместе с наездом. Звук перелистывания на каждый лист.
 *
 *  Своё, не из Why&How: другой почерк (Reenie Beanie), машинописный подзаголовок,
 *  страницы из рисунков канала. Записи на полях — только реальные факты из
 *  наших роликов, выдумывать нельзя (правило про тексты карточек). */
export const INK = '#26223A';
export const RUST = '#963E28';
export const HAND = '"Reenie Beanie", cursive';
export const TYPE = '"Special Elite", monospace';
const ease = Easing.bezier(0.45, 0, 0.25, 1);
/** Переворот листа: быстрый старт, мягкая посадка — лист не должен «щёлкать». */
const flipEase = Easing.bezier(0.35, 0.05, 0.35, 1);

/** zoom — масштаб рисунка на лицевой стороне: последний кадр ролика бывает уже с наездом камеры. */
export type Page = {img: string; note: string; zoom?: number};
const PAGES: Page[] = [
  {img: 'survival/ship.jpg', note: 'Aug 13, 1913'},
  {img: 'survival/desert.jpg', note: 'Day 9. No water.'},
  {img: 'survival/camp.jpg', note: 'Shipwreck Camp'},
  {img: 'survival/island.jpg', note: 'Wrangel Island, 1921'},
  {img: 'survival/walk.jpg', note: '700 miles of ice'},
];

export type NotebookIntroProps = {
  title?: string;
  subtitle?: string;
  /** вариант звука: буква набора flip_<x>1/2.mp3 или 'riffle' — одно сплошное пролистывание */
  sfx?: string;
};

/** Кадры начала переворота каждого листа: сначала неторопливо, потом быстрее. */
export const FLIP = 12;
const STARTS = [4, 13, 21, 28, 34];

export const Leaf: React.FC<{page: Page; start: number}> = ({page, start}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const t = interpolate(frame, [start, start + FLIP], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: flipEase});
  if (t >= 1) return null;
  const angle = -180 * t;
  const lift = Math.sin(Math.PI * t);
  const front = t < 0.5;
  return (
    <AbsoluteFill style={{perspective: width * 3, perspectiveOrigin: '50% 50%'}}>
      <AbsoluteFill style={{
        transformOrigin: '0% 50%',
        transform: `rotateY(${angle}deg)`,
        transformStyle: 'preserve-3d',
      }}>
        {front ? (
          <AbsoluteFill style={{overflow: 'hidden', filter: `brightness(${1 - 0.3 * lift})`}}>
            <Img src={staticFile(page.img)} style={{width, height, objectFit: 'cover', transform: `scale(${page.zoom ?? 1})`}} />
            <div style={{
              position: 'absolute', left: width * 0.075, top: height * 0.06,
              fontFamily: HAND, fontSize: height * 0.07, color: INK, opacity: 0.88,
              transform: 'rotate(-2deg)', whiteSpace: 'nowrap',
            }}>{page.note}</div>
          </AbsoluteFill>
        ) : (
          <AbsoluteFill style={{transform: 'scaleX(-1)', filter: `brightness(${1 - 0.3 * lift})`}}>
            <Img src={staticFile('survival/page_back.jpg')} style={{width, height, objectFit: 'cover'}} />
          </AbsoluteFill>
        )}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** Тень от поднятого листа на следующей странице — со стороны корешка. */
export const Shade: React.FC<{start: number}> = ({start}) => {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [start, start + FLIP], [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: flipEase});
  const k = Math.sin(Math.PI * t);
  if (k <= 0) return null;
  return <AbsoluteFill style={{
    background: `linear-gradient(90deg, rgba(20,16,10,${0.45 * k}) 0%, rgba(20,16,10,0) ${20 + 45 * (1 - t)}%)`,
  }} />;
};

const TitlePage: React.FC<{title: string; subtitle: string; subFrom: number; subTo: number}> =
  ({title, subtitle, subFrom, subTo}) => {
    const frame = useCurrentFrame();
    const {width, height} = useVideoConfig();
    const s = interpolate(frame, [subFrom, subTo], [0, 1],
      {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
    return (
      <AbsoluteFill>
        <Img src={staticFile('survival/page_blank.jpg')} style={{width, height, objectFit: 'cover'}} />
        <AbsoluteFill style={{
          alignItems: 'center', justifyContent: 'flex-start', paddingTop: height * 0.27,
          transform: 'rotate(1.5deg)',
        }}>
          <div style={{fontFamily: HAND, fontSize: height * 0.2, color: INK, opacity: 0.92,
            lineHeight: 1, whiteSpace: 'nowrap'}}>{title}</div>
          <svg width={width * 0.62} height={height * 0.04} style={{marginTop: height * 0.005}}>
            <path d={`M ${width * 0.01} ${height * 0.012} Q ${width * 0.31} ${height * 0.03} ${width * 0.61} ${height * 0.016}`}
              stroke={RUST} strokeWidth={height * 0.0065} fill="none" strokeLinecap="round" opacity={0.9} />
          </svg>
          <div style={{
            marginTop: height * 0.035, fontFamily: TYPE, fontSize: height * 0.043,
            color: '#463C37', letterSpacing: `${0.08 + 0.1 * (1 - s)}em`,
            opacity: 0.85 * s, filter: `blur(${(1 - s) * 5}px)`,
          }}>{subtitle}</div>
        </AbsoluteFill>
      </AbsoluteFill>
    );
  };

export const NotebookIntro: React.FC<NotebookIntroProps> = ({title, subtitle, sfx = 'b'}) => {
  const frame = useCurrentFrame();
  const {height, durationInFrames} = useVideoConfig();
  const flipsEnd = STARTS[STARTS.length - 1] + FLIP;

  // Наезд камеры на название: начинается, пока ложится последний лист.
  const zoom = interpolate(frame, [flipsEnd - 3, durationInFrames - 4], [1, 1.26],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.2, 1)});
  const subFrom = flipsEnd + 8;
  const subTo = subFrom + 26;

  return (
    <AbsoluteFill style={{backgroundColor: '#1A1612', overflow: 'hidden'}}>
      <AbsoluteFill style={{transform: `scale(${zoom})`, transformOrigin: `50% ${height * 0.43}px`}}>
        <TitlePage title={title || "Survivor's Notebook"} subtitle={subtitle || 'TRUE STORIES OF SURVIVAL'}
          subFrom={subFrom} subTo={subTo} />
        {/* Листы кладём от последнего к первому: верхний — первый */}
        {PAGES.map((p, i) => ({p, i})).reverse().map(({p, i}) => (
          <React.Fragment key={i}>
            <Shade start={STARTS[i]} />
            <Leaf page={p} start={STARTS[i]} />
          </React.Fragment>
        ))}
      </AbsoluteFill>
      {sfx === 'riffle' ? (
        <Sequence from={STARTS[0] - 1}><Audio src={staticFile('survival/riffle.mp3')} /></Sequence>
      ) : STARTS.map((s, i) => (
        <Sequence key={i} from={s - 1}>
          <Audio src={staticFile(`survival/flip_${sfx}${i % 2 + 1}.mp3`)}
            volume={0.8 + 0.2 * ((i * 7) % 3) / 2} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
