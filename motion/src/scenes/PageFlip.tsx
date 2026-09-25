import React from 'react';
import {AbsoluteFill, Audio, Img, Sequence, staticFile, useVideoConfig} from 'remotion';
import {Leaf, Shade} from './NotebookIntro';

/** Граница смысловых блоков в роликах Survivor's Notebook: последний рисунок
 *  блока переворачивается и открывает первый рисунок следующего — тем же
 *  движением и звуком, что в интро. Наезд камеры на уходящем листе сохраняется
 *  через zoom, чтобы на стыке не было скачка. */
export type PageFlipProps = {from: string; to: string; zoom?: number; seconds?: number};

export const PageFlip: React.FC<PageFlipProps> = ({from, to, zoom = 1}) => {
  const {width, height} = useVideoConfig();
  const start = 2;
  return (
    <AbsoluteFill style={{backgroundColor: '#1A1612'}}>
      <Img src={staticFile(to)} style={{width, height, objectFit: 'cover'}} />
      <Shade start={start} />
      <Leaf page={{img: from, note: '', zoom}} start={start} />
      <Sequence from={start - 1}><Audio src={staticFile('survival/flip_b2.mp3')} volume={0.8} /></Sequence>
    </AbsoluteFill>
  );
};
