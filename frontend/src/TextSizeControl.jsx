import React, {useLayoutEffect, useState} from 'react';
import './textSize.css';

const STORAGE_KEY = 'term-agent.text-size';

function savedSize() {
  try {return localStorage.getItem(STORAGE_KEY) === 'large' ? 'large' : 'normal';}
  catch {return 'normal';}
}

export function TextSizeControl() {
  const [size, setSize] = useState(savedSize);
  useLayoutEffect(() => {
    document.documentElement.dataset.textSize = size;
    try {localStorage.setItem(STORAGE_KEY, size);} catch { /* The control still works without storage. */ }
  }, [size]);
  return <div role="group" aria-label="Text size" className="text-size-control">
    <span>Text size</span>
    <button type="button" aria-pressed={size === 'normal'} onClick={() => setSize('normal')}>Normal</button>
    <button type="button" aria-pressed={size === 'large'} onClick={() => setSize('large')}>Large</button>
  </div>;
}
