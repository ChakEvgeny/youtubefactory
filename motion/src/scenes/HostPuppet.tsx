import React from 'react';
import {AbsoluteFill, Audio, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

/** Ведущий-марионетка: липсинк из посимвольного выравнивания ElevenLabs.
 *
 *  Почему не нейросетевой i2v: на рисованном персонаже он плывёт лицом и стилем,
 *  замеренный брак 45%, и липсинка там нет вообще. Здесь рот рисуется той же
 *  краской поверх кадра, попадание в звук точное, стоит ноль.
 *
 *  Висемы грубые — пять состояний. Для «примерного попадания в губы» этого
 *  достаточно, зритель считывает ритм речи, а не артикуляцию. */
type Align = {characters: string[]; character_start_times_seconds: number[]; character_end_times_seconds: number[]};
export type HostPuppetProps = {
  bg: string; align: string; audio?: string;
  mouth: [number, number, number, number];
  eyeL: [number, number, number, number];
  eyeR: [number, number, number, number];
  /** прямоугольник накладки рта — тот же, из которого вырезаны все шесть артикуляций */
  patch?: [number, number, number, number];
  offset?: number;      // с какой секунды звука начинаем
};

const NAVY = '#1B2A5E';
const DARK = '#121C3F';
const BEARD = '#C19255';   // замерено по кадру: тон вокруг рта
const LIP = '#8C4A38';

/** Раскрытие рта и округлость по букве. Гласные открывают, губные закрывают. */
/* Шесть нарисованных ртов из листа артикуляций (anim/viseme_chart.jpg):
   0 сомкнут · 1 приоткрыт · 2 приоткрыт с зубами · 3 широко «а» · 4 трубочкой «у» · 5 растянут «и».
   Раньше рот был SVG-эллипсом и выглядел чертежом, а не рисунком. */
const viseme = (c: string): number => {
  const ch = c.toLowerCase();
  if ('aáà'.includes(ch)) return 3;
  if ('eiy'.includes(ch)) return 5;
  if ('ou'.includes(ch)) return 4;
  if ('w'.includes(ch)) return 4;
  if ('mbp'.includes(ch)) return 0;
  if ('fv'.includes(ch)) return 2;
  if ('lnrdtszcghjkqx'.includes(ch)) return 1;
  return 0;
};

export const HostPuppet: React.FC<HostPuppetProps> = ({bg, align, audio, mouth, eyeL, eyeR, patch, offset = 0}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const t = frame / fps + offset;

  const [data, setData] = React.useState<Align | null>(null);
  React.useEffect(() => {
    fetch(staticFile(align)).then((r) => r.json()).then(setData);
  }, [align]);

  // текущая буква и мягкое сглаживание: без него рот дёргается покадрово
  // Сглаживание считаем детерминированно от времени, а не через useRef: Remotion
  // рендерит кадры независимо и параллельно, состояние между ними не живёт.
  const at = (tt: number) => {
    if (!data) return 0;
    const i = data.character_start_times_seconds.findIndex(
      (s2, k2) => tt >= s2 && tt < data.character_end_times_seconds[k2]);
    return i >= 0 ? viseme(data.characters[i]) : 0;
  };
  const cur = at(t);
  // держим рот открытым чуть дольше буквы, иначе на быстрой речи он мерцает
  const idx = cur !== 0 ? cur : (at(t - 0.04) || at(t - 0.08) || 0);

  const px = (b: [number, number, number, number]) => ({
    x: b[0] * width, y: b[1] * height, w: (b[2] - b[0]) * width, h: (b[3] - b[1]) * height,
  });
  const m = px(mouth), el = px(eyeL), er = px(eyeR);

  // рот: перекрываем исходный с запасом, иначе из-под накладки торчит нарисованный
  const mcx = m.x + m.w / 2, mcy = m.y + m.h / 2;

  // моргание: короткое, каждые 3.2 с со сдвигом
  const bt = (t + 1.1) % 3.2;
  const blink = bt < 0.14 ? Math.sin((bt / 0.14) * Math.PI) : 0;

  // лёгкое дыхание и покачивание всего кадра — персонаж перестаёт быть статуей
  const sway = Math.sin(t * 0.9) * 0.0022 + Math.sin(t * 2.3) * 0.0008;
  const bob = Math.sin(t * 1.35) * 0.0016;
  const scale = 1.012 + Math.sin(t * 0.7) * 0.0035;

  return (
    <AbsoluteFill style={{backgroundColor: '#F2ECE0'}}>
      <AbsoluteFill style={{transform: `translate(${sway * width}px, ${bob * height}px) scale(${scale})`}}>
        <Img src={staticFile(bg)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
        {/* Накладка ставится ровно в тот прямоугольник, из которого вырезана, и в родном
            размере. Раньше все шесть ртов растягивались в одну коробку — отсюда прыгал
            масштаб, а чужая борода вокруг давала светлый ореол. */}
        {(() => {
          const pb = patch ?? [mouth[0] - 0.055, mouth[1] - 0.075, mouth[2] + 0.055, mouth[3] + 0.075];
          const p0 = px(pb as [number, number, number, number]);
          return (
            <Img src={staticFile(`work/visemes/v${idx}.png`)}
                 style={{position: 'absolute', left: p0.x, top: p0.y, width: p0.w, height: p0.h}} />
          );
        })()}
        <svg width={width} height={height} style={{position: 'absolute', inset: 0}}>
          {blink > 0.02 && [el, er].map((e, i) => (
            <rect key={i} x={e.x} y={e.y} width={e.w} height={e.h * blink}
                  fill={BEARD} stroke={NAVY} strokeWidth={height * 0.0022} />
          ))}
        </svg>
      </AbsoluteFill>
      {audio && <Audio src={staticFile(audio)} startFrom={Math.round(offset * fps)} />}
    </AbsoluteFill>
  );
};
