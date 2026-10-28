function loadImage(source) {
  return new Promise((resolve,reject)=>{
    const image=new Image();image.crossOrigin='anonymous';
    const timeout=setTimeout(()=>reject(new Error('Imagem indisponível.')),10000);
    image.onload=()=>{clearTimeout(timeout);resolve(image);};
    image.onerror=()=>{clearTimeout(timeout);reject(new Error('Imagem indisponível.'));};image.src=source;
  });
}
function lines(ctx,text,width) {
  const result=[];
  for(const paragraph of text.split('\n')) {
    let line='';
    for(const word of paragraph.split(/\s+/)) {
      const next=line?`${line} ${word}`:word;
      if(line&&ctx.measureText(next).width>width){result.push(line);line='';}
      if(ctx.measureText(word).width>width) {
        for(const character of Array.from(word)) {
          if(line&&ctx.measureText(line+character).width>width){result.push(line);line='';}
          line+=character;
        }
      }else line+=(line?' ':'')+word;
    }
    result.push(line.trimEnd());
  }
  return result;
}
function ellipsis(ctx,value,width,suffix='...') {
  const chars=Array.from(value);
  while(chars.length&&ctx.measureText(chars.join('')+suffix).width>width)chars.pop();
  return chars.join('').trimEnd()+suffix;
}
function squareImage(ctx,image,x,y,size) {
  const side=Math.min(image.naturalWidth,image.naturalHeight);
  ctx.drawImage(image,(image.naturalWidth-side)/2,(image.naturalHeight-side)/2,side,side,x,y,size,size);
}
export async function createShareImage({post,track,artwork,author,photo,initials,provider}) {
  await document.fonts.ready;
  const style=getComputedStyle(document.documentElement),color=name=>style.getPropertyValue(name).trim();
  const serif=style.getPropertyValue('--serif'),sans=style.getPropertyValue('--sans');
  await Promise.all([document.fonts.load(`27px ${serif}`),document.fonts.load(`12px ${sans}`)]);
  const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
  // Fixed portrait with the album at the center and the comment below it.
  const width=490,height=612.5,inset=30,contentWidth=width-inset*2,scale=1080/width;
  const coverSize=240,coverX=(width-coverSize)/2,coverTop=26;
  ctx.font=`24px ${serif}`;const allTitles=lines(ctx,track.title,contentWidth),titles=allTitles.slice(0,2);
  if(allTitles.length>2)titles[1]=ellipsis(ctx,titles[1],contentWidth);
  ctx.font=`12px ${sans}`;const allArtists=lines(ctx,track.artist,contentWidth),artists=allArtists.slice(0,1);
  if(allArtists.length>1)artists[0]=ellipsis(ctx,artists[0],contentWidth);
  const titleTop=coverTop+coverSize+18,artistTop=titleTop+titles.length*29+5,providerTop=artistTop+19;
  const authorTop=providerTop+(provider==='spotify'?23:14)+14,textTop=authorTop+26+14;
  ctx.font=`18px ${serif}`;const reflection=lines(ctx,post.text?`“${post.text}”`:'',contentWidth);
  const actionsTop=height-74,maxLines=Math.max(1,Math.floor((actionsTop-textTop-16)/28)),shown=reflection.slice(0,maxLines);
  canvas.width=1080;canvas.height=1350;ctx.scale(scale,scale);
  ctx.fillStyle=color('--bg');ctx.fillRect(0,0,width,height);
  ctx.strokeStyle=color('--border');ctx.lineWidth=1;ctx.strokeRect(.5,.5,width-1,height-1);
  ctx.save();ctx.beginPath();ctx.roundRect(coverX,coverTop,coverSize,coverSize,6);ctx.clip();
  try{ctx.globalAlpha=post.lyricExcerpt?0.22:1;squareImage(ctx,await loadImage(artwork),coverX,coverTop,coverSize);ctx.globalAlpha=1;}
  catch{ctx.fillStyle=color('--surface');ctx.fillRect(coverX,coverTop,coverSize,coverSize);}
  ctx.restore();ctx.textBaseline='top';ctx.fillStyle=color('--text');ctx.font=`24px ${serif}`;ctx.textAlign='center';
  if(post.lyricExcerpt) {
    ctx.save();ctx.font=`16px ${serif}`;
    const verses=lines(ctx,`“${post.lyricExcerpt}”`,coverSize-44),verseHeight=Math.min(verses.length,8)*21.6,top=coverTop+(coverSize-verseHeight)/2;
    verses.slice(0,8).forEach((line,i)=>ctx.fillText(i===7&&verses.length>8?ellipsis(ctx,line,coverSize-44,'...”'):line,width/2,top+i*21.6));ctx.restore();
  }
  titles.forEach((line,i)=>ctx.fillText(line,width/2,titleTop+i*29));
  ctx.fillStyle=color('--muted');ctx.font=`12px ${sans}`;
  artists.forEach(line=>ctx.fillText(line,width/2,artistTop));
  if(provider==='spotify') {
    try{const logo=await loadImage('assets/spotify-white.svg');ctx.drawImage(logo,(width-74)/2,providerTop,74,23);}catch{}
  }else{ctx.font=`10px ${sans}`;ctx.fillText('Ouvir no Deezer ↗',width/2,providerTop);}
  ctx.font=`12px ${sans}`;const names=lines(ctx,author,contentWidth-35),name=names.length>1?ellipsis(ctx,names[0],contentWidth-35):names[0];
  const nameWidth=ctx.measureText(name).width,date=post.date||'agora';ctx.font=`9px ${sans}`;
  const authorX=(width-(26+9+Math.max(nameWidth,ctx.measureText(date).width)))/2;
  ctx.save();ctx.beginPath();ctx.arc(authorX+13,authorTop+13,13,0,Math.PI*2);ctx.clip();
  let avatar;
  if(photo){try{avatar=await loadImage(photo);}catch{}}
  if(avatar)squareImage(ctx,avatar,authorX,authorTop,26);
  ctx.restore();ctx.strokeStyle=color('--border');ctx.beginPath();ctx.arc(authorX+13,authorTop+13,12.5,0,Math.PI*2);ctx.stroke();
  if(!avatar){ctx.fillStyle=color('--muted');ctx.font=`9px ${sans}`;ctx.fillText(initials||author.slice(0,2).toUpperCase(),authorX+13,authorTop+8);}
  ctx.textAlign='left';
  ctx.fillStyle=color('--text');ctx.font=`12px ${sans}`;
  ctx.fillText(name,authorX+35,authorTop);
  ctx.fillStyle=color('--muted');ctx.font=`9px ${sans}`;ctx.fillText(date,authorX+35,authorTop+16);
  ctx.textAlign='center';ctx.fillStyle=color('--text');ctx.font=`18px ${serif}`;
  shown.forEach((line,i)=>ctx.fillText(i===shown.length-1&&reflection.length>maxLines?ellipsis(ctx,line,contentWidth,'...”'):line,width/2,textTop+i*28));
  ctx.save();ctx.translate((width-79)/2,actionsTop);ctx.strokeStyle=color('--muted');ctx.lineWidth=1.2;
  ctx.stroke(new Path2D('M20.8 4.8a5.5 5.5 0 0 0-7.8 0L12 5.9l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.4a5.5 5.5 0 0 0 0-7.8Z'));
  ctx.translate(55,0);ctx.stroke(new Path2D('M12 16V3m-4 4 4-4 4 4M5 13v7h14v-7'));ctx.restore();
  ctx.fillStyle=color('--muted');ctx.font=`11px ${sans}`;ctx.fillText('Ver ressoa completa ↗',width/2,height-30);
  return new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
}
export function downloadFile(blob,filename) {
  const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),3000);
}
