import { ensureTrackDetails } from './track-context.js';
import { getSpotifyStatus, playSpotifyExcerpt, stopSpotifyPlayback } from './spotify.js';

export function createAudioExcerpt({ host, musicDetails, stopPreview, onChange }) {
  host.innerHTML='<details class="audio-excerpt"><summary>Escolher trecho de áudio</summary><p class="form-note audio-note"></p><div class="audio-controls" hidden><label>Início <output class="audio-start-label"></output><input class="audio-start" type="range" min="0" max="29" step="0.1" value="0" aria-label="Início do trecho de áudio"></label><label>Fim <output class="audio-end-label"></output><input class="audio-end" type="range" min="1" max="30" step="0.1" value="30" aria-label="Fim do trecho de áudio"></label><div class="audio-excerpt-actions"><button type="button" class="text-button audio-listen">Ouvir seleção</button><button type="button" class="text-button audio-reset">Usar prévia inteira</button></div></div></details>';
  const details=host.querySelector('details'),note=host.querySelector('.audio-note'),controls=host.querySelector('.audio-controls');
  const start=host.querySelector('.audio-start'),end=host.querySelector('.audio-end'),listen=host.querySelector('.audio-listen');
  for(const [field,range] of [['audio-start-label',start],['audio-end-label',end]]){
    const output=host.querySelector('.'+field),input=document.createElement('input');input.type='text';input.className=field+' audio-time';input.placeholder='0:00';input.setAttribute('aria-label',range===start?'Tempo inicial, minutos e segundos':'Tempo final, minutos e segundos');output.replaceWith(input);
    input.addEventListener('input',()=>input.setCustomValidity(''));
    input.addEventListener('change',()=>{
      const raw=input.value.trim().replace(',','.');const parts=raw.split(':');
      const value=parts.length===2&&/^\d+$/.test(parts[0])&&/^\d{1,2}(?:\.\d)?$/.test(parts[1])&&Number(parts[1])<60?Number(parts[0])*60+Number(parts[1]):parts.length===1&&/^\d+(?:\.\d)?$/.test(raw)?Number(raw):NaN;
      const max=Number(range.max),min=Number(range.min);
      if(!Number.isFinite(value)||value<min||value>max){input.setCustomValidity('Use minutos:segundos dentro da faixa disponível.');input.reportValidity();return;}
      input.setCustomValidity('');range.value=String(value);range.dispatchEvent(new Event('input',{bubbles:true}));
    });
    input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();input.blur();}});
  }
  const audio=document.createElement('audio');audio.preload='metadata';audio.volume=.5;host.append(audio);
  let index=null,value=null,generation=0,loaded=false,limit=30,full=false,sdkPlaying=false,span=30;
  const connect=document.createElement('button');connect.type='button';connect.className='text-button';connect.dataset.connectSpotify='true';connect.textContent='Conectar Spotify';connect.hidden=true;details.append(connect);
  const label=n=>`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}${Math.round(n*10)%10?'.'+Math.round(n*10)%10:''}`;
  function stop(){audio.pause();if(sdkPlaying)stopSpotifyPlayback();sdkPlaying=false;listen.textContent='Ouvir seleção';}
  function sync(){host.querySelector('.audio-start-label').value=label(Number(start.value));host.querySelector('.audio-end-label').value=label(Number(end.value));host.querySelectorAll('.audio-time').forEach(input=>input.setCustomValidity(''));}
  async function load(){
    if(index===null){note.textContent='Escolha uma música primeiro.';return;}
    if(loaded)return;
    const token=generation;note.textContent='Carregando prévia…';
    try {
      const track=await ensureTrackDetails(index).catch(()=>musicDetails[index]);if(token!==generation)return;
      full=track?.provider==='spotify';
      if(full){
        const status=await getSpotifyStatus();if(token!==generation)return;
        if(!status.connected){note.textContent=status.configured?'Conecte seu Spotify Premium para escolher qualquer ponto da faixa.':'A seleção da faixa completa estará disponível quando a conexão Spotify estiver ativa.';connect.hidden=!status.configured;return;}
        connect.hidden=true;limit=Number(track.duration)||0;
        if(limit<1){note.textContent='Não foi possível obter a duração desta faixa.';return;}
        start.max=String(limit-1);end.max=String(limit);start.value=String(Math.min(value?.start||0,limit-1));end.value=String(Math.min(value?.end||30,limit));span=Number(end.value)-Number(start.value);sync();
        note.textContent='Escolha de 1 a 30 segundos em qualquer ponto da faixa. A reprodução usa sua conta Spotify Premium.';
        host.querySelector('.audio-reset').textContent='Usar player padrão';loaded=true;controls.hidden=false;return;
      }
      if(track?.provider!=='deezer'||!track.previewUrl){note.textContent='Esta faixa não tem uma prévia que permita selecionar o áudio.';return;}
      connect.hidden=true;host.querySelector('.audio-reset').textContent='Usar prévia inteira';
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
    if(full&&input===start)end.value=String(Math.min(limit,Number(start.value)+span));
    if(input===start&&Number(start.value)>Number(end.value)-1)end.value=String(Math.min(limit,Number(start.value)+1));
    if(input===end&&Number(end.value)<Number(start.value)+1)start.value=String(Math.max(0,Number(end.value)-1));
    if(full&&Number(end.value)-Number(start.value)>30)start.value=String(Number(end.value)-30);
    span=Number(end.value)-Number(start.value);stop();value={start:Number(start.value),end:Number(end.value),...(full?{source:'spotify'}:{})};sync();onChange?.();
  });
  listen.addEventListener('click',async()=>{
    if(!audio.paused||sdkPlaying){stop();return;}stopPreview();
    if(full){
      value={start:Number(start.value),end:Number(end.value),source:'spotify'};onChange?.();const token=generation;
      try{await playSpotifyExcerpt(musicDetails[index],value,playing=>{if(token===generation){sdkPlaying=playing;listen.textContent=playing?'Pausar seleção':'Ouvir seleção';}});}catch(error){note.textContent=error.message;connect.hidden=false;}return;
    }
    audio.currentTime=Number(start.value);
    try{await audio.play();listen.textContent='Pausar seleção';}catch{note.textContent='Não foi possível reproduzir esta prévia.';}
  });
  host.querySelector('.audio-reset').addEventListener('click',()=>{stop();value=null;span=30;start.value='0';end.value=String(full?Math.min(30,limit):limit);sync();onChange?.();});
  window.addEventListener('spotifychange',()=>{if(details.open){loaded=false;void load();}});
  document.addEventListener('ressoaplaybackstop',stop);
  return {get value(){return value?{...value}:null;},stop,set(track,selection=null){
    generation++;stop();audio.removeAttribute('src');audio.load();index=track;loaded=false;limit=30;full=musicDetails[track]?.provider==='spotify';span=selection?selection.end-selection.start:30;connect.hidden=true;
    value=selection?{...selection}:null;start.max='29';end.max='30';start.value=String(value?.start||0);end.value=String(value?.end||30);sync();
    controls.hidden=true;note.textContent=track===null?'Escolha uma música primeiro.':'Ajuste o trecho dentro da prévia disponível.';
    if(details.open)void load();
  }};
}
