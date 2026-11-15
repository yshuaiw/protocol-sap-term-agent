// Backend anchors count Unicode code points; JS string.slice counts UTF-16 units.
export const sourceSlice = (text, start, end) => Array.from(text).slice(start, end).join('');
