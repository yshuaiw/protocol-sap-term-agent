export function rangesValid(selections, info) {
  if(selections.length !== 2)return false;
  for(const s of selections) {
    if(!info[s.file_index] || !Number.isInteger(s.start) || !Number.isInteger(s.end) ||
      s.start < 1 || s.end < s.start || s.end > info[s.file_index].pages)return false;
  }
  const [a,b]=selections;
  return a.file_index !== b.file_index || Math.max(a.start,b.start) > Math.min(a.end,b.end);
}

export function boundaryNotice(results) {
  const suggestions=results.map(x=>x.ai_suggestion).filter(Boolean);
  if(!suggestions.length)return '';
  const proposed=suggestions.reduce((n,s)=>n+s.documents.filter(d=>d.applicable).length,0);
  return proposed ? `${proposed} document range proposal${proposed===1?'':'s'} returned. Review the evidence before applying; selected ranges have not changed.` :
    'No usable independent-document ranges returned. Review the source, limitations and any embedded sections below; selected ranges have not changed.';
}
