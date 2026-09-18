import React from 'react';
import {useCurrentFrame} from 'remotion';

export const Grain: React.FC<{opacity?: number}> = ({opacity = 0.05}) => {
  const f = useCurrentFrame();
  const id = `n${f % 6}`;
  return (
    <svg style={{position: 'absolute', inset: 0, width: '100%', height: '100%', opacity,
      mixBlendMode: 'overlay', pointerEvents: 'none'}}>
      <filter id={id}>
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={f % 6} />
      </filter>
      <rect width="100%" height="100%" filter={`url(#${id})`} />
    </svg>
  );
};
