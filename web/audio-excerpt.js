import { ensureTrackDetails } from './track-context.js';

export function createAudioExcerpt({ host, musicDetails, stopPreview, onChange }) {
  host.innerHTML='<details class="audio-excerpt"><summary>Escolher trecho de áudio</summary><p class="form-note audio-note"></p><div class="audio-controls" hidden><label>Início <output class="audio-start-label"></output><input class="audio-start" type="range" min="0" max="29" step="0.1" value="0" aria-label="Início do trecho de áudio"></label><label>Fim <output class="audio-end-label"></output><input class="audio-end" type="range" min="1" max="30" step="0.1" value="30" aria-label="Fim do trecho de áudio"></label><div class="audio-excerpt-actions"><button type="button" class="text-button audio-listen">Ouvir seleção</button><button type="button" class="text-button audio-reset">Usar prévia inteira</button></div></div></details>';
  const details=host.querySelector('details'),note=host.querySelector('.audio-note'),controls=host.querySelector('.audio-controls');
  const start=host.querySelector('.audio-start'),end=host.querySelector('.audio-end'),listen=host.querySelector('.audio-listen');
  const audio=document.createElement('audio');audio.preload='metadata';audio.volume=.5;host.append(audio);
  let index=null,value=null,generation=0,loaded=false,limit=30;
  const label=n=>`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`;
  function stop(){audio.pause();listen.textContent='Ouvir seleção';}
  function sync(){host.querySelector('.audio-start-label').textContent=label(Number(start.value));host.querySelector('.audio-end-label').textContent=label(Number(end.value));}
  async function load(){
    if(index===null){note.textContent='Escolha uma música primeiro.';return;}
    if(loaded)return;
    const token=generation;note.textContent='Carregando prévia…';
    try {
      const track=await ensureTrackDetails(index).catch(()=>musicDetails[index]);if(token!==generation)return;
      if(track?.provider!=='deezer'||!track.previewUrl){note.textContent='Esta faixa não tem uma prévia que permita selecionar o áudio.';return;}
      note.textContent='Escolha dentro da prévia disponível. Os tempos são relativos à prévia, não à música completa.';
      audio.src=track.previewUrl;loaded=true;controls.hidden=false;
    }catch{if(token===generation)note.textContent='Não foi possível carregar a prévia. Feche e abra para tentar novamente.';}
  }
  audio.addEventListener('loadedmetadata',()=>{
    limit=Math.min(30,Number.isFinite(audio.duration)?audio.duration:30);
    if(limit<1){controls.hidden=true;note.textContent='Prévia indisponível.';return;}
    start.max=String(limit-1);end.max=String(limit);end.value=String(Math.min(Number(end.value),limit));start.value=String(Math.min(Number(start.value),Number(end.value)-1));
    if(value)value={start:Number(start.value),end:Number(end.value)};sync();
  });
  audio.addEventListener('timeupdate',()=>{if(audio.currentTime>=Number(end.value)-.04){stop();audio.currentTime=Number(start.value);}});
  audio.addEventListener('ended',stop);audio.addEventListener('pause',()=>{listen.textContent='Ouvir seleção';});
  audio.addEventListener('error',()=>{stop();note.textContent='Não foi possível ouvir esta prévia. Sua seleção continua salva.';});
  details.addEventListener('toggle',()=>{if(details.open)void load();else stop();});
  for(const input of [start,end])input.addEventListener('input',()=>{
    if(input===start&&Number(start.value)>Number(end.value)-1)end.value=String(Math.min(limit,Number(start.value)+1));
    if(input===end&&Number(end.value)<Number(start.value)+1)start.value=String(Math.max(0,Number(end.value)-1));
    stop();value={start:Number(start.value),end:Number(end.value)};sync();onChange?.();
  });
  listen.addEventListener('click',async()=>{
    if(!audio.paused){stop();return;}stopPreview();audio.currentTime=Number(start.value);
    try{await audio.play();listen.textContent='Pausar seleção';}catch{note.textContent='Não foi possível reproduzir esta prévia.';}
  });
  host.querySelector('.audio-reset').addEventListener('click',()=>{stop();value=null;start.value='0';end.value=String(limit);sync();onChange?.();});
  document.addEventListener('ressoaplaybackstop',stop);
  return {get value(){return value?{...value}:null;},stop,set(track,selection=null){
    generation++;stop();audio.removeAttribute('src');audio.load();index=track;loaded=false;limit=30;
    value=selection?{...selection}:null;start.max='29';end.max='30';start.value=String(value?.start||0);end.value=String(value?.end||30);sync();
    controls.hidden=true;note.textContent=track===null?'Escolha uma música primeiro.':'Ajuste o trecho dentro da prévia disponível.';
    if(details.open)void load();
  }};
}
