import { api, getAccount } from './session.js';

let cached=null,statusJob=null,owner=null,notify=()=>{};
let sdkJob=null,player=null,deviceId=null,playerJob=null,current=null,clock=null,revision=0;
let playQueue=Promise.resolve(),popup=null,checkConnection=null;
const activatedPlayers=new WeakSet();
const publicConnectionsPaused=true;
export const setSpotifyFeedback=callback=>{notify=callback;};

function updateControls(status){
  document.querySelectorAll('[data-spotify-shortcut]').forEach(button=>{
    button.hidden=!status.configured;button.dataset.connected=String(status.connected);
    const label=status.connected?'Spotify conectado · gerenciar conexão':'Conectar Spotify';
    button.setAttribute('aria-label',label);button.title=label;
  });
  document.querySelectorAll('[data-spotify-connection]').forEach(host=>{
    host.hidden=!status.configured;
    const label=host.querySelector('[data-spotify-status]');if(label)label.textContent=status.connected?`Spotify conectado${status.displayName?' · '+status.displayName:''}`:'Conecte sua conta Spotify para buscar músicas.';
    host.querySelectorAll('[data-connect-spotify]').forEach(button=>{button.hidden=status.connected;button.textContent='Conectar Spotify';});
    host.querySelectorAll('[data-disconnect-spotify]').forEach(button=>button.hidden=!status.connected);
  });
}
async function refreshConnection(error){
  if(error.code!=='SPOTIFY_AUTH_REQUIRED')return;
  try{const status=await getSpotifyStatus(true);window.dispatchEvent(new CustomEvent('spotifychange',{detail:status}));}catch{}
}
function releasePlayer(instance=player){
  if(player===instance){player=null;deviceId=null;}
  try{instance?.disconnect();}catch{}
}
export async function getSpotifyStatus(force=false){
  const user=getAccount()?.user.id;
  if(owner!==user){const previous=owner;owner=user;cached=null;statusJob=null;if(previous!==null)stopSpotifyPlayback();player?.disconnect();player=null;deviceId=null;playerJob=null;}
  if(cached&&!force)return cached;
  if(statusJob){if(!force)return statusJob;await statusJob.catch(()=>{});}
  const job=api('/api/spotify/status').then(status=>{
    if(owner!==user)return {configured:false,connected:false};cached=status;
    if(!status.connected&&player){stopSpotifyPlayback();releasePlayer();}
    updateControls(status);return status;
  });statusJob=job;void job.finally(()=>{if(statusJob===job)statusJob=null;}).catch(()=>{});
  return job;
}

export async function connectSpotify(){
  if(publicConnectionsPaused){notify('Aguarde! Estamos preparando a liberação da conexão com o Spotify.');return;}
  if(popup&&!popup.closed){popup.focus();return;}
  const account=getAccount()?.user.id;
  popup=window.open('about:blank','ressoa-spotify','popup,width=520,height=720');
  if(!popup)throw new Error('Permita a janela de conexão com Spotify e tente novamente.');
  const target=popup;target.document.title='Ressoa + Spotify';target.document.body.textContent='Conectando ao Spotify…';
  let url;
  try{({url}=await api('/api/spotify/connect',{method:'POST',body:{}}));}
  catch(error){target.close();popup=null;throw error;}
  return new Promise((resolve,reject)=>{
    let timeout,closed,poll,received=false,settled=false,checking=false;
    const finish=(error)=>{if(settled)return;settled=true;window.removeEventListener('message',receive);clearTimeout(timeout);clearInterval(closed);clearInterval(poll);if(checkConnection===check)checkConnection=null;if(popup===target)popup=null;try{target.close();}catch{}error?reject(error):resolve();};
    const complete=status=>{
      if(settled)return;
      if(getAccount()?.user.id!==account){finish(new Error('Sua conta Ressoa mudou. Conecte o Spotify novamente.'));return;}
      window.dispatchEvent(new CustomEvent('spotifychange',{detail:status}));document.getElementById('spotify-dialog')?.close();finish();
    };
    const verify=async wasClosed=>{
      if(settled||received||checking)return;checking=true;
      try{
        if(getAccount()?.user.id!==account){finish(new Error('Sua conta Ressoa mudou. Conecte o Spotify novamente.'));return;}
        const status=await getSpotifyStatus(true);if(settled||received)return;
        if(status.connected)complete(status);
        else if(wasClosed)finish(new Error('A conexão foi fechada antes da confirmação. Tente novamente.'));
      }catch(error){if(wasClosed)finish(error);}finally{checking=false;}
    };
    const check=()=>verify(target.closed&&document.hasFocus());checkConnection=check;
    const receive=async event=>{
      if(settled||received||event.origin!==location.origin||event.source!==target||event.data?.type!=='ressoa-spotify')return;
      received=true;clearInterval(closed);
      if(!event.data.connected){finish(new Error(event.data.message||'Conexão cancelada.'));return;}
      try{const status=await getSpotifyStatus(true);if(!status.connected)throw new Error('O Spotify ainda não confirmou a conexão. Tente novamente.');complete(status);}
      catch(error){finish(error);}
    };
    window.addEventListener('message',receive);
    timeout=setTimeout(()=>finish(new Error('A conexão expirou. Tente novamente.')),600000);
    closed=setInterval(()=>{if(target.closed&&!document.hidden&&document.hasFocus())void verify(true);},700);
    poll=setInterval(()=>{if(!document.hidden)void check();},3000);
    target.location.href=url;
  });
}

async function refreshOnReturn(){
  if(document.hidden||!getAccount()?.user.id)return;
  if(checkConnection){void checkConnection();return;}
  const previous=cached;if(!previous)return;
  try{const status=await getSpotifyStatus(true);if(status.connected!==previous.connected||status.configured!==previous.configured||status.displayName!==previous.displayName)window.dispatchEvent(new CustomEvent('spotifychange',{detail:status}));}catch{}
}
window.addEventListener('focus',()=>{void refreshOnReturn();});
document.addEventListener('visibilitychange',()=>{void refreshOnReturn();});

function loadSDK(){
  if(window.Spotify?.Player)return Promise.resolve(window.Spotify);
  if(sdkJob)return sdkJob;
  sdkJob=new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src='https://sdk.scdn.co/spotify-player.js';script.async=true;
    const fail=()=>{clearTimeout(timer);script.remove();sdkJob=null;reject(new Error('O player do Spotify não carregou. Tente novamente.'));};
    const timer=setTimeout(fail,18000);
    window.onSpotifyWebPlaybackSDKReady=()=>{clearTimeout(timer);resolve(window.Spotify);};script.onerror=fail;document.head.append(script);
  });return sdkJob;
}
async function getPlayer(){
  if(player&&deviceId)return {player,deviceId};
  if(playerJob)return playerJob;
  playerJob=(async()=>{
    const status=await getSpotifyStatus();
    if(!status.connected){const dialog=document.getElementById('spotify-dialog');if(status.configured&&dialog&&!dialog.open)dialog.showModal();throw Object.assign(new Error('Conecte sua conta Spotify para ouvir este trecho.'),{code:'SPOTIFY_AUTH_REQUIRED'});}
    const account=owner,sdk=await loadSDK();if(owner!==account)throw new Error('A conta mudou. Tente novamente.');releasePlayer();
    return await new Promise((resolve,reject)=>{
      const instance=new sdk.Player({name:'Ressoa',volume:.5,getOAuthToken:callback=>{api('/api/spotify/token').then(data=>{if(player===instance&&owner===account&&getAccount()?.user.id===account)callback(data.accessToken);else instance.disconnect();}).catch(error=>{void refreshConnection(error);fail(error.message);});}});
      player=instance;
      let settled=false,failed=false;
      const fail=message=>{if(failed)return;failed=true;clearTimeout(timer);const active=player===instance;if(active)stopSpotifyPlayback();releasePlayer(instance);if(settled){if(active)notify(message);}else reject(new Error(message));};
      const timer=setTimeout(()=>fail('O player do Spotify demorou para conectar. Confira sua conexão e toque no play novamente.'),20000);
      instance.addListener('ready',event=>{clearTimeout(timer);if(player!==instance)return;deviceId=event.device_id;settled=true;resolve({player:instance,deviceId});});
      instance.addListener('not_ready',()=>{if(player===instance){deviceId=null;stopSpotifyPlayback();}});
      instance.addListener('authentication_error',()=>fail('O Spotify não aceitou a conexão do player. Tente o play novamente; se continuar, desconecte e conecte sua conta.'));
      instance.addListener('account_error',()=>fail('Este trecho exige uma conta Spotify Premium.'));
      instance.addListener('initialization_error',()=>fail('Este navegador não conseguiu iniciar o áudio protegido do Spotify. No iPhone, abra o Ressoa diretamente no Safari atualizado, fora do aplicativo Google, Instagram ou WhatsApp.'));
      instance.addListener('autoplay_failed',()=>{if(player!==instance)return;activatedPlayers.delete(instance);stopSpotifyPlayback();document.dispatchEvent(new Event('ressoaplaybackstop'));notify('O navegador pausou o áudio. Toque no play para ouvir.');});
      instance.addListener('playback_error',()=>{if(player!==instance)return;stopSpotifyPlayback();document.dispatchEvent(new Event('ressoaplaybackstop'));notify('O Spotify não conseguiu tocar esta faixa. Toque no play para tentar novamente ou escolha outra música.');});
      instance.addListener('player_state_changed',state=>{if(player===instance)readClipState(state);});
      instance.connect().then(connected=>{if(!connected)fail('Não foi possível conectar o player do Spotify.');}).catch(()=>fail('Não foi possível conectar o player do Spotify.'));
    });
  })();const job=playerJob;void job.finally(()=>{if(playerJob===job)playerJob=null;}).catch(()=>{});return job;
}
function readClipState(state){
  const clip=current;if(!clip||state?.track_window?.current_track?.id!==clip.trackId||!Number.isFinite(state.position))return;
  if(clip.finished){clip.onState?.(false);return;}
  const age=Date.now()-clip.requestedAt;
  // A seek can briefly report the position of the previously selected excerpt.
  if(!clip.started&&age<10000&&(state.position<clip.start*1000-250||state.position>clip.start*1000+age+2000))return;
  clip.started=true;clip.onState?.(!state.paused);
  if(!state.paused&&state.position>clip.start*1000+100){clip.advanced=true;clearTimeout(clip.startTimer);}
  if(!clip.ending)clip.onProgress?.(Math.max(0,Math.min(clip.end-clip.start,state.position/1000-clip.start)));
  if(state.position>=clip.end*1000)void endClip();
}
async function endClip(){
  if(!current||current.ending)return;
  const clip=current;clip.ending=true;clip.finished=true;clearTimeout(clip.startTimer);clip.onProgress?.(clip.end-clip.start);clearInterval(clock);clock=null;
  const job=playQueue.catch(()=>{}).then(async()=>{if(current!==clip)return;await player?.pause();if(current===clip)await player?.seek(clip.start*1000);});playQueue=job.catch(()=>{});
  try{await job;}catch{stopSpotifyPlayback();}finally{if(current===clip){clip.onState?.(false);clip.ending=false;}}
}
export function stopSpotifyPlayback(){
  const active=Boolean(current),instance=player;revision++;clearInterval(clock);clock=null;clearTimeout(current?.startTimer);current?.onState?.(false);current=null;
  if(active){const job=playQueue.catch(()=>{}).then(()=>instance?.pause());playQueue=job.catch(()=>{});}
}
function activateSpotifyPlayback(){
  const instance=player;if(!instance)return null;
  const gesture=navigator.userActivation?.isActive!==false;
  let job;
  // Keep this call in the original click handler, before any asynchronous work.
  try{job=Promise.resolve(instance.activateElement());}catch(error){job=Promise.reject(error);}
  if(gesture)job=job.then(()=>{if(player===instance)activatedPlayers.add(instance);});
  void job.catch(()=>{});return {instance,job};
}
async function activateReadyPlayer(ready,activation){
  const requireGesture=()=>Object.assign(new Error('Player pronto. Toque no play novamente para liberar o áudio neste navegador.'),{code:'SPOTIFY_GESTURE_REQUIRED'});
  if(activation?.instance===ready.player){
    try{await activation.job;}catch(error){if(error.name==='NotAllowedError')throw requireGesture();throw error;}
  }
  const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
  if(ios&&!activatedPlayers.has(ready.player))throw requireGesture();
  if(activation?.instance!==ready.player&&!activatedPlayers.has(ready.player))await ready.player.activateElement();
}
export function prepareSpotifyPlayback(){
  const activation=activateSpotifyPlayback();
  return Promise.all([activation?.job,getSpotifyStatus()]).then(([,status])=>status.connected?getPlayer():null);
}
export function playSpotifyExcerpt(track,excerpt,onState,onProgress){
  const activation=activateSpotifyPlayback();
  const token=++revision;
  const job=playQueue.catch(()=>{}).then(async()=>{
    if(token!==revision)return;
    let ready=await getPlayer();if(token!==revision)return;await activateReadyPlayer(ready,activation);if(token!==revision)return;
    const state=await ready.player.getCurrentState();if(token!==revision)return;
    const identifier=track.spotifyId||track.id,local=state?.track_window?.current_track?.id===identifier;
    const same=current?.trackId===identifier&&current.start===excerpt.start&&current.end===excerpt.end;
    if(same&&local&&!state.paused){clearInterval(clock);clock=null;clearTimeout(current.startTimer);await ready.player.pause();onState?.(false);return;}
    clearInterval(clock);clock=null;clearTimeout(current?.startTimer);current?.onState?.(false);current=null;
    if(local){
      // A loaded browser player can restart locally, without another Connect play request.
      await ready.player.seek(excerpt.start*1000);if(token!==revision)return;await ready.player.resume();
    }else{
      for(let attempt=0;attempt<2;attempt++){
        try{await api('/api/spotify/play',{method:'POST',body:{trackId:identifier,deviceId:ready.deviceId,start:excerpt.start}});break;}
        catch(error){
          if(token!==revision)return;
          if(error.code==='SPOTIFY_DEVICE_UNAVAILABLE'&&!attempt){releasePlayer(ready.player);ready=await getPlayer();if(token!==revision)return;await activateReadyPlayer(ready);if(token!==revision)return;continue;}
          await refreshConnection(error);throw error;
        }
      }
    }
    if(token!==revision){await ready.player.pause();return;}
    const clip={trackId:identifier,start:excerpt.start,end:excerpt.end,onState,onProgress,ending:false,started:false,advanced:false,requestedAt:Date.now()};current=clip;onProgress?.(0);onState?.(true);
    clip.startTimer=setTimeout(()=>{if(current!==clip||clip.advanced)return;stopSpotifyPlayback();notify('O áudio não começou neste navegador. Toque no play para tentar novamente.');},12000);
    let checking=false;
    clock=setInterval(async()=>{
      if(checking||!current||token!==revision)return;checking=true;
      try{const state=await player.getCurrentState();if(token!==revision||!current||!state)return;if(state.track_window?.current_track?.id!==current.trackId){if(current.started||Date.now()-current.requestedAt>10000)stopSpotifyPlayback();return;}readClipState(state);}
      catch{stopSpotifyPlayback();}finally{checking=false;}
    },200);
  });playQueue=job.catch(()=>{});return job;
}

document.addEventListener('click',async event=>{
  const shortcut=event.target.closest('[data-spotify-shortcut]'),connect=event.target.closest('[data-connect-spotify]'),disconnect=event.target.closest('[data-disconnect-spotify]');
  if(!shortcut&&!connect&&!disconnect)return;event.preventDefault();const button=shortcut||connect||disconnect;
  if(shortcut?.dataset.connected==='true'){
    const dialog=document.getElementById('spotify-dialog');if(dialog&&!dialog.open)dialog.showModal();return;
  }
  button.disabled=true;
  try{
    if(connect||shortcut)await connectSpotify();
    else{await api('/api/spotify/connection',{method:'DELETE',body:{}});stopSpotifyPlayback();releasePlayer();const status=await getSpotifyStatus(true);window.dispatchEvent(new CustomEvent('spotifychange',{detail:status}));}
  }catch(error){notify(error.message);}finally{button.disabled=false;}
});
