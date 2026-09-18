import React from 'react';
import {Composition} from 'remotion';
import {Card, CardProps} from './scenes/Card';
import {Overlay, OverlayProps} from './scenes/Overlay';
import {Diagram, DiagramProps} from './scenes/Diagram';
import {Outro, OutroProps} from './scenes/Outro';
import {Bumper, BumperProps} from './scenes/Bumper';

type Props = CardProps & {seconds?: number};
type OProps = OverlayProps & {seconds?: number};
type DProps = DiagramProps & {seconds?: number};
type UProps = OutroProps & {seconds?: number};
type BProps = BumperProps & {seconds?: number};

const frames = (s: unknown) => Math.max(Math.round(((s as number) ?? 5) * 24), 24);

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Card"
      component={Card as React.FC<Record<string, unknown>>}
      durationInFrames={120}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{lines: ['ARCTIC OCEAN', 'NORTH OF SIBERIA', '1923'], kicker: '', seconds: 5} as Props}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as Props).seconds)})}
    />
    <Composition
      id="Overlay"
      component={Overlay as React.FC<Record<string, unknown>>}
      durationInFrames={120}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{lines: ['SPENT     2,200', 'WON       2,150', 'RESULT      -50'],
                     kicker: 'MESICK, MI 2003', side: 'left', pos: 'lower', seconds: 5} as OProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as OProps).seconds)})}
    />
    <Composition
      id="Diagram"
      component={Diagram as React.FC<Record<string, unknown>>}
      durationInFrames={120}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{transparent: true, kind: 'gauge', title: 'the ceiling',
        items: [{label: 'your kidney, max', value: 1200, max: 1200},
                {label: 'seawater', value: 1150, max: 1200}], seconds: 4} as DProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as DProps).seconds)})}
    />
    <Composition
      id="Outro"
      component={Outro as React.FC<Record<string, unknown>>}
      durationInFrames={120}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{thanks: 'Thanks for watching', cta: 'Subscribe for more', seconds: 5} as UProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as UProps).seconds)})}
    />
    <Composition
      id="Bumper"
      component={Bumper as React.FC<Record<string, unknown>>}
      durationInFrames={96}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{words: ['Why', '&', 'How'], font: 'Sriracha', seconds: 4} as BProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as BProps).seconds)})}
    />
  </>
);
