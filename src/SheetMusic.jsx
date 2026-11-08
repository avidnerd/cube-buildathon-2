import React, { useEffect, useRef, useState } from 'react';
import abcjs from 'abcjs';

/** Reusable score renderer; accepts ABC from melodyToAbc(). */
export function SheetMusic({ abc }) {
  const container = useRef(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.round(entry.contentRect.width))));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const element = container.current;
    abcjs.renderAbc(element, abc, {
      responsive: 'resize', staffwidth: width - 30, add_classes: true,
      wrap: { minSpacing: 1.8, maxSpacing: 2.7, preferredMeasuresPerLine: 4 },
    });
    return () => element.replaceChildren();
  }, [abc, width]);
  return <div className="notation" ref={container} aria-label="Melody sheet music" />;
}
