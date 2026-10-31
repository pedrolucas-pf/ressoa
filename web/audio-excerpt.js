import { ensureTrackDetails } from './track-context.js';
import { getSpotifyStatus, playSpotifyExcerpt, stopSpotifyPlayback, prepareSpotifyPlayback } from './spotify.js';

export function createAudioExcerpt({ host, musicDetails, stopPreview, onChange }) {
  const playIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 11 7-11 7Z" fill="currentColor" stroke="none"/></svg>';
  const pauseIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6v12M16 6v12" stroke-width="3"/></svg>';
  host.innerHTML=`<details class="audio-excerpt"><summary>Escolher trecho de áudio</summary><p class="form-note audio-note"></p><div class="audio-controls" hidden><div class="audio-range-heading"><output class="audio-selected-time"></output><span class="audio-length">30 s</span></div><div class="audio-timeline"><div class="audio-rail" aria-hidden="true"><span class="audio-window"></span></div><input class="audio-position" type="range" min="0" max="0" step="0.1" value="0" aria-label="Posição do trecho na música"></div><div class="audio-scale" aria-hidden="true"><span>0:00</span><span class="audio-total"></span></div><div class="audio-excerpt-actions"><button type="button" class="icon-button audio-listen" aria-label="Ouvir trecho" title="Ouvir trecho" aria-pressed="false">${playIcon}</button><button type="button" class="text-button audio-reset">Usar player padrão</button></div></div></details>`;
  const details=host.querySelector('details'),note=host.querySelector('.audio-note'),controls=host.querySelector('.audio-controls');
  const slider=host.querySelector('.audio-position'),timeline=host.querySelector('.audio-timeline'),listen=host.querySelector('.audio-listen');
  const selectedTime=host.querySelector('.audio-selected-time'),length=host.querySelector('.audio-length'),total=host.querySelector('.audio-total');
  const reset=host.querySelector('.audio-reset');
  const audio=document.createElement('audio');audio.preload='metadata';audio.volume=.5;host.append(audio);
  const connect=document.createElement('button');connect.type='button';connect.className='text-button';connect.dataset.connectSpotify='true';connect.textContent='Conectar Spotify';connect.hidden=true;details.append(connect);
  let index=null,value=null,generation=0,playGeneration=0,loaded=false,loading=null,limit=30,span=30,position=0,full=false,sdkActive=false,sdkPlaying=false,pendingPlay=false;
  let pointer=null,keying=false,changed=false;
  const rangeKeys=['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'];
  const round=n=>Math.round(n*100)/100;
  const label=n=>{const tenths=Math.round(n*10);return `${Math.floor(tenths/600)}:${String(Math.floor(tenths/10)%60).padStart(2,'0')}${tenths%10?','+tenths%10:''}`;};
  const selection=()=>({start:round(position),end:round(position+span),...(full?{source:'spotify'}:{})});

  function showPlaying(playing){
    sdkPlaying=playing;listen.innerHTML=playing?pauseIcon:playIcon;listen.setAttribute('aria-pressed',String(playing));
    const label=playing?'Pausar trecho':'Ouvir trecho';listen.setAttribute('aria-label',label);listen.title=label;listen.classList.toggle('playing',playing);
  }
  function stop(){playGeneration++;pendingPlay=false;audio.pause();if(sdkActive)stopSpotifyPlayback();sdkActive=false;showPlaying(false);listen.removeAttribute('aria-busy');}
  function cancel(){pointer=null;keying=false;changed=false;stop();}
  function prepare(){if(full)void prepareSpotifyPlayback().catch(()=>{});}
  function syncTimeline(){
    const width=timeline.getBoundingClientRect().width;
    const windowWidth=Math.min(width,Math.max(36,width*span/limit));
    timeline.style.setProperty('--excerpt-width',windowWidth+'px');
    timeline.style.setProperty('--excerpt-offset',(limit>span?(width-windowWidth)*position/(limit-span):0)+'px');
  }
  function sync(){
    selectedTime.value=`${label(position)} — ${label(position+span)}`;
    length.textContent=`${round(span).toString().replace('.',',')} s`;total.textContent=label(limit);
    slider.value=String(position);slider.setAttribute('aria-valuetext',`${label(position)} a ${label(position+span)}, ${round(span)} segundos`);
    syncTimeline();
  }
  function configure(duration){
    limit=Math.floor(Math.min(86400,duration)*100)/100;
    // Keep previously saved shorter excerpts when editing an existing Ressoa.
    span=Math.min(limit,value?Math.max(1,Math.min(30,value.end-value.start)):30);
    position=Math.max(0,Math.min(value?.start||0,limit-span));
    slider.max=String(Math.max(0,limit-span));slider.disabled=limit-span<.1;
    timeline.dataset.fixed=String(slider.disabled);
    if(value)value=selection();
    controls.hidden=false;sync();
  }
  async function load(){
    if(index===null){note.textContent='Escolha uma música primeiro.';return;}
    if(loaded)return;if(loading)return loading;
    const token=generation;note.textContent='Carregando áudio…';
    const job=(async()=>{
      try{
        const track=await ensureTrackDetails(index).catch(()=>musicDetails[index]);if(token!==generation)return;
        full=track?.provider==='spotify';
        if(full){
          const status=await getSpotifyStatus();if(token!==generation)return;
          if(!status.connected){note.textContent=status.configured?'Conecte seu Spotify Premium para escolher qualquer ponto da faixa.':'A seleção da faixa completa estará disponível quando a conexão Spotify estiver ativa.';connect.hidden=!status.configured;return;}
          connect.hidden=true;const duration=Number(track.duration)||0;
          if(duration<1){note.textContent='Não foi possível obter a duração desta faixa.';return;}
          note.textContent='Arraste e solte para ouvir.';reset.textContent='Usar player padrão';loaded=true;configure(duration);return;
        }
        if(track?.provider!=='deezer'||!track.previewUrl){note.textContent='Esta faixa não tem uma prévia de áudio disponível.';return;}
        connect.hidden=true;reset.textContent='Usar prévia inteira';
        note.textContent='Prévia Deezer. Para escolher outra parte da música, use Spotify.';
        loaded=true;configure(30);audio.src=track.previewUrl;
      }catch{if(token===generation)note.textContent='Não foi possível carregar o áudio. Feche e abra para tentar novamente.';}
    })();
    loading=job;try{await job;}finally{if(loading===job)loading=null;}
  }
  function commit(){if(changed){changed=false;void startPlayback();}}
  slider.addEventListener('pointerdown',event=>{if(event.button!==0||!event.isPrimary)return;pointer=event.pointerId;changed=false;prepare();});
  window.addEventListener('pointerup',event=>{if(pointer===event.pointerId){pointer=null;commit();}});
  window.addEventListener('pointercancel',event=>{if(pointer===event.pointerId)cancel();});
  slider.addEventListener('input',()=>{stop();position=Math.max(0,Math.min(Number(slider.value),limit-span));value=selection();changed=true;sync();onChange?.();});
  slider.addEventListener('change',()=>{if(pointer===null&&!keying)commit();});
  slider.addEventListener('keydown',event=>{
    if(!rangeKeys.includes(event.key))return;
    keying=true;prepare();
    if(!['PageUp','PageDown'].includes(event.key))return;
    event.preventDefault();slider.value=String(position+(event.key==='PageUp'?5:-5));slider.dispatchEvent(new Event('input',{bubbles:true}));
  });
  slider.addEventListener('keyup',event=>{if(rangeKeys.includes(event.key)){keying=false;commit();}});
  slider.addEventListener('blur',()=>{if(keying){keying=false;changed=false;}});
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(syncTimeline).observe(timeline);
  else window.addEventListener('resize',syncTimeline);
  audio.addEventListener('loadedmetadata',()=>{
    if(full||!loaded)return;
    const duration=Math.min(30,Number.isFinite(audio.duration)?audio.duration:30);
    if(duration<1){controls.hidden=true;note.textContent='Prévia indisponível.';return;}
    configure(duration);
    if(pendingPlay||!audio.paused)audio.currentTime=position;
  });
  audio.addEventListener('timeupdate',()=>{if(audio.currentTime>=position+span-.04){audio.pause();audio.currentTime=position;}});
  audio.addEventListener('play',()=>showPlaying(true));audio.addEventListener('pause',()=>showPlaying(false));audio.addEventListener('ended',()=>showPlaying(false));
  audio.addEventListener('error',()=>{if(full||!loaded)return;cancel();note.textContent='Não foi possível ouvir esta prévia. Sua seleção continua salva.';});
  async function loadAndPlay(){
    const token=generation,attempt=playGeneration;await load();
    if(token===generation&&attempt===playGeneration&&details.open&&loaded)void startPlayback();
  }
  details.querySelector('summary').addEventListener('click',prepare);
  details.addEventListener('toggle',()=>{if(details.open)void loadAndPlay();else cancel();});
  async function startPlayback(){
    if(!loaded||!details.open||controls.hidden||index===null||host.closest('dialog')?.open===false)return;
    stopPreview();const token=generation,attempt=++playGeneration;pendingPlay=true;showPlaying(true);listen.setAttribute('aria-busy','true');
    if(full){
      note.textContent='Arraste e solte para ouvir.';connect.hidden=true;
      value=selection();onChange?.();sdkActive=true;
      try{await playSpotifyExcerpt(musicDetails[index],value,playing=>{if(token===generation&&attempt===playGeneration)showPlaying(playing);});}
      catch(error){if(token===generation&&attempt===playGeneration){sdkActive=false;showPlaying(false);note.textContent=error.message;connect.hidden=false;}}
      finally{if(token===generation&&attempt===playGeneration){pendingPlay=false;listen.removeAttribute('aria-busy');}}
      return;
    }
    audio.currentTime=position;
    try{await audio.play();}
    catch{if(token===generation&&attempt===playGeneration){showPlaying(false);note.textContent='Não foi possível iniciar a prévia. Toque no play para tentar novamente.';}}
    finally{if(token===generation&&attempt===playGeneration){pendingPlay=false;listen.removeAttribute('aria-busy');}}
  }
  listen.addEventListener('click',()=>{
    if(pendingPlay||!audio.paused||sdkPlaying)cancel();else void startPlayback();
  });
  reset.addEventListener('click',()=>{cancel();value=null;configure(limit);onChange?.();});
  window.addEventListener('spotifychange',()=>{if(!full)return;generation++;cancel();loaded=false;loading=null;controls.hidden=true;if(details.open)void loadAndPlay();});
  document.addEventListener('ressoaplaybackstop',cancel);
  return {get value(){return value?{...value}:null;},stop:cancel,async alignTo(start){
    if(!Number.isFinite(start)||start<0||musicDetails[index]?.provider!=='spotify')return false;
    const token=generation;await load();if(token!==generation||!loaded||!full)return false;
    cancel();span=Math.min(30,limit);position=Math.max(0,Math.min(start,limit-span));value=selection();configure(limit);
    const wasOpen=details.open;details.open=true;onChange?.();if(wasOpen)void startPlayback();return true;
  },set(track,excerpt=null){
    generation++;cancel();index=track;loaded=false;loading=null;full=musicDetails[track]?.provider==='spotify';limit=30;span=30;position=0;connect.hidden=true;
    value=excerpt?{...excerpt}:null;audio.removeAttribute('src');audio.load();controls.hidden=true;
    note.textContent=track===null?'Escolha uma música primeiro.':'Arraste para escolher o trecho de áudio.';
    prepare();if(details.open)void loadAndPlay();
  }};
}
