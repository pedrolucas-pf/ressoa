import { api, getAccount } from './session.js';

let cached=null,statusJob=null,owner=null,notify=()=>{};
let sdkJob=null,player=null,deviceId=null,playerJob=null,current=null,clock=null,revision=0;
let playQueue=Promise.resolve(),popup=null;
export const setSpotifyFeedback=callback=>{notify=callback;};

function updateControls(status){
  document.querySelectorAll('[data-spotify-connection]').forEach(host=>{
    host.hidden=!status.configured;
    const label=host.querySelector('[data-spotify-status]');if(label)label.textContent=status.connected?`Spotify conectado${status.displayName?' · '+status.displayName:''}`:'Conecte seu Spotify Premium para escolher qualquer ponto da faixa.';
    host.querySelectorAll('[data-connect-spotify]').forEach(button=>{button.hidden=false;button.textContent=status.connected?'Reconectar Spotify':'Conectar Spotify';});
    host.querySelectorAll('[data-disconnect-spotify]').forEach(button=>button.hidden=!status.connected);
  });
}
export async function getSpotifyStatus(force=false){
  const user=getAccount()?.user.id;
  if(owner!==user){const previous=owner;owner=user;cached=null;statusJob=null;if(previous!==null)stopSpotifyPlayback();player?.disconnect();player=null;deviceId=null;playerJob=null;}
  if(cached&&!force)return cached;
  if(statusJob){if(!force)return statusJob;await statusJob.catch(()=>{});}
  statusJob=api('/api/spotify/status').then(status=>{
    if(owner!==user)return {configured:false,connected:false};cached=status;updateControls(status);return status;
  }).finally(()=>{statusJob=null;});
  return statusJob;
}

export async function connectSpotify(){
  if(popup&&!popup.closed){popup.focus();return;}
  popup=window.open('about:blank','ressoa-spotify','popup,width=520,height=720');
  if(!popup)throw new Error('Permita a janela de conexão com Spotify e tente novamente.');
  const target=popup;target.document.title='Ressoa + Spotify';target.document.body.textContent='Conectando ao Spotify…';
  let url;
  try{({url}=await api('/api/spotify/connect',{method:'POST',body:{}}));}
  catch(error){target.close();popup=null;throw error;}
  return new Promise((resolve,reject)=>{
    let timeout,closed,received=false;
    const finish=(error)=>{window.removeEventListener('message',receive);clearTimeout(timeout);clearInterval(closed);if(popup===target)popup=null;target.close();error?reject(error):resolve();};
    const receive=async event=>{
      if(received||event.origin!==location.origin||event.source!==target||event.data?.type!=='ressoa-spotify')return;
      received=true;clearInterval(closed);
      if(!event.data.connected){finish(new Error(event.data.message||'Conexão cancelada.'));return;}
      try{const status=await getSpotifyStatus(true);window.dispatchEvent(new CustomEvent('spotifychange',{detail:status}));document.getElementById('spotify-dialog')?.close();finish();}
      catch(error){finish(error);}
    };
    window.addEventListener('message',receive);
    timeout=setTimeout(()=>finish(new Error('A conexão expirou. Tente novamente.')),600000);
    closed=setInterval(()=>{if(target.closed)finish(new Error('A conexão foi fechada. Tente novamente.'));},700);
    target.location.href=url;
  });
}

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
    if(!status.connected){const dialog=document.getElementById('spotify-dialog');if(status.configured&&dialog&&!dialog.open)dialog.showModal();throw new Error('Conecte sua conta Spotify Premium para ouvir este trecho.');}
    const account=owner,sdk=await loadSDK();if(owner!==account)throw new Error('A conta mudou. Tente novamente.');player?.disconnect();
    return await new Promise((resolve,reject)=>{
      const instance=new sdk.Player({name:'Ressoa',volume:.5,getOAuthToken:callback=>{api('/api/spotify/token').then(data=>{if(owner===account&&getAccount()?.user.id===account)callback(data.accessToken);else instance.disconnect();}).catch(()=>fail('Reconecte sua conta do Spotify.'));}});
      player=instance;
      let settled=false;
      const timer=setTimeout(()=>{instance.disconnect();if(player===instance){player=null;deviceId=null;}reject(new Error('O dispositivo do Spotify não ficou pronto. Tente novamente.'));},20000);
      const fail=message=>{clearTimeout(timer);instance.disconnect();if(player===instance){stopSpotifyPlayback();player=null;deviceId=null;}if(settled)notify(message);else reject(new Error(message));};
      instance.addListener('ready',event=>{clearTimeout(timer);if(player!==instance)return;deviceId=event.device_id;settled=true;resolve({player:instance,deviceId});});
      instance.addListener('not_ready',()=>{if(player===instance){deviceId=null;stopSpotifyPlayback();}});
      instance.addListener('authentication_error',()=>fail('Reconecte sua conta do Spotify.'));
      instance.addListener('account_error',()=>fail('Este trecho exige uma conta Spotify Premium.'));
      instance.addListener('initialization_error',()=>fail('Seu navegador não conseguiu iniciar o Spotify.'));
      instance.addListener('autoplay_failed',()=>notify('Toque em ouvir novamente para iniciar o Spotify.'));
      instance.addListener('player_state_changed',state=>{
        if(current&&state?.track_window?.current_track?.id===current.trackId){current.started=true;current.onState?.(!state.paused);if(state.position>=current.end*1000)void endClip();}
      });
      instance.connect().then(connected=>{if(!connected)fail('Não foi possível conectar o player do Spotify.');}).catch(()=>fail('Não foi possível conectar o player do Spotify.'));
    });
  })().finally(()=>{playerJob=null;});return playerJob;
}
async function endClip(){
  if(!current||current.ending)return;
  const clip=current;clip.ending=true;clearInterval(clock);clock=null;
  const job=playQueue.catch(()=>{}).then(async()=>{if(current!==clip)return;await player?.pause();if(current===clip)await player?.seek(clip.start*1000);});playQueue=job.catch(()=>{});
  try{await job;}catch{stopSpotifyPlayback();}finally{if(current===clip){clip.onState?.(false);clip.ending=false;}}
}
export function stopSpotifyPlayback(){
  revision++;clearInterval(clock);clock=null;current?.onState?.(false);current=null;
  try{player?.pause()?.catch(()=>{});}catch{}
}
export function playSpotifyExcerpt(track,excerpt,onState){
  if(player)void player.activateElement();
  const token=++revision;
  const job=playQueue.catch(()=>{}).then(async()=>{
    if(token!==revision)return;
    const ready=await getPlayer();if(token!==revision)return;await ready.player.activateElement();
    const same=current?.trackId===track.spotifyId&&current.start===excerpt.start&&current.end===excerpt.end;
    if(same){const state=await player.getCurrentState();if(state&&!state.paused){clearInterval(clock);clock=null;await player.pause();onState?.(false);return;}}
    clearInterval(clock);clock=null;current?.onState?.(false);current=null;
    await api('/api/spotify/play',{method:'POST',body:{trackId:track.spotifyId||track.id,deviceId:ready.deviceId,start:excerpt.start}});
    if(token!==revision){await ready.player.pause();return;}
    current={trackId:track.spotifyId||track.id,start:excerpt.start,end:excerpt.end,onState,ending:false,started:false,requestedAt:Date.now()};onState?.(true);
    let checking=false;
    clock=setInterval(async()=>{
      if(checking||!current||token!==revision)return;checking=true;
      try{const state=await player.getCurrentState();if(token!==revision||!current||!state)return;if(state.track_window?.current_track?.id!==current.trackId){if(current.started||Date.now()-current.requestedAt>10000)stopSpotifyPlayback();return;}current.started=true;onState?.(!state.paused);if(state.position>=current.end*1000)await endClip();}
      catch{stopSpotifyPlayback();}finally{checking=false;}
    },200);
  });playQueue=job.catch(()=>{});return job;
}

document.addEventListener('click',async event=>{
  const connect=event.target.closest('[data-connect-spotify]'),disconnect=event.target.closest('[data-disconnect-spotify]');
  if(!connect&&!disconnect)return;event.preventDefault();const button=connect||disconnect;button.disabled=true;
  try{
    if(connect)await connectSpotify();
    else{stopSpotifyPlayback();player?.disconnect();player=null;deviceId=null;await api('/api/spotify/connection',{method:'DELETE',body:{}});const status=await getSpotifyStatus(true);window.dispatchEvent(new CustomEvent('spotifychange',{detail:status}));}
  }catch(error){notify(error.message);}finally{button.disabled=false;}
});
