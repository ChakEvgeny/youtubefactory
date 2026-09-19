import React from 'react';
import {Composition} from 'remotion';
import {Card, CardProps} from './scenes/Card';
import {Overlay, OverlayProps} from './scenes/Overlay';
import {Diagram, DiagramProps} from './scenes/Diagram';
import {Outro, OutroProps} from './scenes/Outro';
import {Bumper, BumperProps} from './scenes/Bumper';
import {NotebookIntro} from './scenes/NotebookIntro';
import {NotebookOutro, NotebookOutroProps} from './scenes/NotebookOutro';
import {Scrap, ScrapProps} from './scenes/Scrap';
import {PageFlip, PageFlipProps} from './scenes/PageFlip';
import {NoirIntro, NoirCut, NoirCutProps, NoirOutro, NoirOutroProps} from './scenes/Noir';
import {Evidence, EvidenceProps} from './scenes/Evidence';

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
    <Composition
      id="NotebookIntro"
      component={NotebookIntro as React.FC<Record<string, unknown>>}
      durationInFrames={108}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{title: "Survivor's Notebook", subtitle: 'TRUE STORIES OF SURVIVAL', sfx: 'b'}}
    />
    <Composition
      id="NotebookOutro"
      component={NotebookOutro as React.FC<Record<string, unknown>>}
      durationInFrames={288}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{last: 'survival/walk.jpg', zoom: 1, end: 'The End', seconds: 6, slots: false} as NotebookOutroProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as NotebookOutroProps).seconds ?? 12)})}
    />
    <Composition
      id="Scrap"
      component={Scrap as React.FC<Record<string, unknown>>}
      durationInFrames={144}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{type: 'date', big: 'Jan 11, 1914', small: '3:15 PM', bg: 'survival/ship.jpg', seconds: 6} as ScrapProps & {seconds: number}}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as {seconds?: number}).seconds ?? 6)})}
    />
    <Composition
      id="PageFlip"
      component={PageFlip as React.FC<Record<string, unknown>>}
      durationInFrames={24}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={{from: 'survival/ship.jpg', to: 'survival/camp.jpg', zoom: 1, seconds: 1} as PageFlipProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as PageFlipProps).seconds ?? 1)})}
    />
    <Composition id="NoirIntro" component={NoirIntro as React.FC<Record<string, unknown>>}
      durationInFrames={108} fps={24} width={1920} height={1080} defaultProps={{}} />
    <Composition id="NoirCut" component={NoirCut as React.FC<Record<string, unknown>>}
      durationInFrames={24} fps={24} width={1920} height={1080}
      defaultProps={{from: 'noir/panel1.jpg', to: 'noir/panel2.jpg', zoom: 1, seconds: 1} as NoirCutProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as NoirCutProps).seconds ?? 1)})} />
    <Composition id="NoirOutro" component={NoirOutro as React.FC<Record<string, unknown>>}
      durationInFrames={144} fps={24} width={1920} height={1080}
      defaultProps={{last: 'noir/panel2.jpg', zoom: 1, seconds: 6} as NoirOutroProps}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as NoirOutroProps).seconds ?? 6)})} />
    <Composition id="Evidence" component={Evidence as React.FC<Record<string, unknown>>}
      durationInFrames={144} fps={24} width={1920} height={1080}
      defaultProps={{type: 'counter', big: '$6', small: "in Allied's petty cash", bg: 'noir/panel2.jpg', seconds: 6} as EvidenceProps & {seconds: number}}
      calculateMetadata={({props}) => ({durationInFrames: frames((props as {seconds?: number}).seconds ?? 6)})} />
  </>
);
