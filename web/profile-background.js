const imageSizes=new Map();
let pageArtwork='',pageLayout=null,pageDimensions={width:1,height:1},pageGeneration=0;

export function cleanBackgroundLayout(value){
  const input=value&&typeof value==='object'?value:{};
  const number=(key,min,max,fallback)=>typeof input[key]==='number'&&Number.isFinite(input[key])?Math.max(min,Math.min(max,input[key])):fallback;
  return {fit:input.fit==='contain'?'contain':'cover',zoom:number('zoom',.5,2.5,1),x:number('x',0,100,50),y:number('y',0,100,50)};
}
function dimensions(artwork){
  if(!imageSizes.has(artwork)){
    const job=new Promise(resolve=>{
      const image=new Image();
      image.onload=()=>resolve({width:image.naturalWidth||1,height:image.naturalHeight||1});
      image.onerror=()=>resolve({width:1,height:1});image.src=artwork;
    });
    if(imageSizes.size>=24)imageSizes.delete(imageSizes.keys().next().value);
    imageSizes.set(artwork,job);
  }
  return imageSizes.get(artwork);
}
function geometry(width,height,size,layout){
  const ratio=layout.fit==='contain'?Math.min(width/size.width,height/size.height):Math.max(width/size.width,height/size.height);
  return {width:size.width*ratio*layout.zoom,height:size.height*ratio*layout.zoom};
}
function paint(host,artwork,layout,width,height,size){
  const image=geometry(width,height,size,layout);
  host.style.setProperty('--profile-art',`url(${JSON.stringify(artwork)})`);
  host.style.setProperty('--profile-size',`${image.width}px ${image.height}px`);
  host.style.setProperty('--profile-position',`${layout.x}% ${layout.y}%`);
  return image;
}
function paintPage(){
  if(pageArtwork)paint(document.body,pageArtwork,pageLayout,document.documentElement.clientWidth,window.innerHeight,pageDimensions);
}
export function setProfileBackground(artwork,layout){
  const token=++pageGeneration;
  pageArtwork=artwork||'';pageLayout=cleanBackgroundLayout(layout);pageDimensions={width:1,height:1};
  document.body.classList.toggle('profile-background',Boolean(pageArtwork));
  if(!pageArtwork){
    for(const key of ['--profile-art','--profile-size','--profile-position'])document.body.style.removeProperty(key);
    return;
  }
  paintPage();
  void dimensions(pageArtwork).then(size=>{if(token!==pageGeneration)return;pageDimensions=size;paintPage();});
}
window.addEventListener('resize',paintPage);

export function createBackgroundEditor(host){
  host.hidden=true;
  host.innerHTML=`<div class="background-fit" role="group" aria-label="Enquadramento da capa"><button type="button" data-background-fit="cover" aria-pressed="true">Preencher</button><button type="button" data-background-fit="contain" aria-pressed="false">Capa inteira</button></div><div class="background-preview"><div class="background-frame" role="img" aria-label="Prévia do enquadramento da capa de fundo"></div></div><p class="form-note background-hint">Arraste a capa para ajustar a posição.</p><div class="background-adjustments"><label>Tamanho<output data-background-output="zoom">100%</output><input type="range" min="50" max="250" value="100" step="1" data-background-key="zoom" aria-label="Tamanho da capa"></label><label>Horizontal<output data-background-output="x">50%</output><input type="range" min="0" max="100" value="50" step="1" data-background-key="x" aria-label="Posição horizontal da capa"></label><label>Vertical<output data-background-output="y">50%</output><input type="range" min="0" max="100" value="50" step="1" data-background-key="y" aria-label="Posição vertical da capa"></label></div><button type="button" class="text-button" data-background-reset>Restaurar enquadramento</button>`;
  const stage=host.querySelector('.background-preview'),frame=host.querySelector('.background-frame');
  let artwork='',layout=cleanBackgroundLayout(),size={width:1,height:1},generation=0,drag=null,image={width:0,height:0};
  function redraw(){
    if(!artwork||!stage.clientWidth||!stage.clientHeight)return;
    const padding=getComputedStyle(stage);
    const availableWidth=stage.clientWidth-parseFloat(padding.paddingLeft)-parseFloat(padding.paddingRight);
    const availableHeight=stage.clientHeight-parseFloat(padding.paddingTop)-parseFloat(padding.paddingBottom);
    const ratio=document.documentElement.clientWidth/window.innerHeight;
    const width=Math.min(availableWidth,availableHeight*ratio),height=width/ratio;
    frame.style.width=width+'px';frame.style.height=height+'px';
    image=paint(frame,artwork,layout,width,height,size);
  }
  function sync(){
    host.querySelectorAll('[data-background-fit]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.backgroundFit===layout.fit)));
    for(const key of ['zoom','x','y']){
      const value=key==='zoom'?Math.round(layout.zoom*100):Math.round(layout[key]);
      host.querySelector(`[data-background-key="${key}"]`).value=String(value);
      host.querySelector(`[data-background-output="${key}"]`).value=value+'%';
    }
    redraw();
  }
  function stop(){
    if(drag&&frame.hasPointerCapture(drag.id))frame.releasePointerCapture(drag.id);
    drag=null;frame.classList.remove('dragging');
  }
  host.addEventListener('click',event=>{
    const fit=event.target.closest('[data-background-fit]');
    if(fit){stop();layout={fit:fit.dataset.backgroundFit,zoom:1,x:50,y:50};sync();}
    if(event.target.closest('[data-background-reset]')){stop();layout=cleanBackgroundLayout();sync();}
  });
  host.addEventListener('input',event=>{
    const key=event.target.dataset.backgroundKey;if(!['zoom','x','y'].includes(key))return;
    stop();layout=cleanBackgroundLayout({...layout,[key]:Number(event.target.value)/(key==='zoom'?100:1)});sync();
  });
  frame.addEventListener('pointerdown',event=>{
    if(!event.isPrimary||event.button!==0||drag)return;
    drag={id:event.pointerId,x:event.clientX,y:event.clientY,layout:{...layout},spaceX:frame.clientWidth-image.width,spaceY:frame.clientHeight-image.height};
    frame.setPointerCapture(event.pointerId);frame.classList.add('dragging');event.preventDefault();
  });
  frame.addEventListener('pointermove',event=>{
    if(drag?.id!==event.pointerId)return;
    const x=Math.abs(drag.spaceX)>1?drag.layout.x+(event.clientX-drag.x)/drag.spaceX*100:layout.x;
    const y=Math.abs(drag.spaceY)>1?drag.layout.y+(event.clientY-drag.y)/drag.spaceY*100:layout.y;
    layout=cleanBackgroundLayout({...layout,x:Math.round(x*100)/100,y:Math.round(y*100)/100});sync();
  });
  for(const event of ['pointerup','pointercancel','lostpointercapture'])frame.addEventListener(event,stop);
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>{stop();redraw();}).observe(stage);
  window.addEventListener('resize',()=>{stop();redraw();});
  return {
    get value(){return {...layout};},stop,
    set(url,value){
      stop();const token=++generation;artwork=url||'';layout=cleanBackgroundLayout(value);size={width:1,height:1};host.hidden=!artwork;sync();
      if(artwork)void dimensions(artwork).then(result=>{if(token!==generation)return;size=result;redraw();});
    }
  };
}
