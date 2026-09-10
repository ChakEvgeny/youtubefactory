import React from "react";
import { Composition } from "remotion";
import { BrandCard, brandSchema } from "./BrandCard";
import { Chart, chartSchema } from "./Chart";
import { Counter, counterSchema } from "./Counter";
import { Callout, calloutSchema } from "./Callout";
import { Collage } from "./Collage";
import { PressCard } from "./PressCard";

const W = 1920, H = 1080, FPS = 30;

// Длительность задаётся из Python: durationInFrames приходит в props.
const calc = ({ props }: any) => ({
  durationInFrames: Math.max(Number(props?.durationInFrames) || FPS * 4, 30),
});

export const Root: React.FC = () => (
  <>
    <Composition id="BrandCard" component={BrandCard} calculateMetadata={calc} durationInFrames={FPS * 4}
      fps={FPS} width={W} height={H}
      defaultProps={{ brand: "BRAND", effect: "crack", palette: ["#D0021B", "#FFFFFF", "#111111"], subtitle: "" }} />
    <Composition id="Chart" component={Chart} calculateMetadata={calc} durationInFrames={FPS * 5}
      fps={FPS} width={W} height={H}
      defaultProps={{ title: "", points: [100, 80, 60, 30, 12], labels: [], palette: ["#D0021B", "#FFFFFF", "#111111"], unit: "" }} />
    <Composition id="Counter" component={Counter} calculateMetadata={calc} durationInFrames={FPS * 4}
      fps={FPS} width={W} height={H}
      defaultProps={{ from: 0, to: 1000000, prefix: "$", suffix: "", label: "", palette: ["#D0021B", "#FFFFFF", "#111111"] }} />
    <Composition id="Collage" component={Collage} calculateMetadata={calc} durationInFrames={FPS * 5}
      fps={FPS} width={W} height={H}
      defaultProps={{ cutout: "", text: "", sub: "", attribution: "", palette: ["#D0021B", "#FFFFFF", "#111111"], side: "right", objectScale: 1, portrait: false, mode: "cutout" }} />
    <Composition id="PressCard" component={PressCard} calculateMetadata={calc} durationInFrames={FPS * 4}
      fps={FPS} width={W} height={H}
      defaultProps={{ shot: "", outlet: "", date: "", headline: "", palette: ["#D0021B", "#FFFFFF", "#111111"] }} />
    <Composition id="Callout" component={Callout} calculateMetadata={calc} durationInFrames={FPS * 3}
      fps={FPS} width={W} height={H}
      defaultProps={{ text: "", note: "", palette: ["#D0021B", "#FFFFFF", "#111111"] }} />
  </>
);
