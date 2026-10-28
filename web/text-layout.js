// Fit a preview to its real rendered bounds; the full text stays in the post model.
export function fitText(element, value) {
  element.textContent=value;
  if(!element.clientHeight||element.scrollHeight<=element.clientHeight+1)return false;
  const characters=Array.from(value);
  let low=0,high=characters.length;
  while(low<high) {
    const middle=Math.ceil((low+high)/2);
    element.textContent=characters.slice(0,middle).join('').trimEnd()+'...';
    if(element.scrollHeight<=element.clientHeight+1)low=middle;else high=middle-1;
  }
  element.textContent=characters.slice(0,low).join('').trimEnd()+'...';
  return true;
}
