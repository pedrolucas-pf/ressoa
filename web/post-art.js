import { fitText } from './text-layout.js';
const escape=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function albumArt({artwork,album,excerpt='',size=400,lazy=false}) {
  const image=`<img class="album-cover" src="${escape(artwork)}" alt="Capa de ${escape(album)}" width="${size}" height="${size}" draggable="false"${lazy?' loading="lazy"':''}>`;
  return excerpt?`<span class="lyric-art">${image}<span class="lyric-quote"><span class="lyric-text" data-full-text="${escape(excerpt)}">${escape(excerpt)}</span></span></span>`:image;
}

export function fitLyricArt(root=document) {
  root.querySelectorAll('.lyric-text').forEach(element=>fitText(element,element.dataset.fullText));
}
