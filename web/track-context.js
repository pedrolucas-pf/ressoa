import { tracks, musicDetails, registerTrack } from './catalog-store.js';
import { catalogTrack } from './catalog.js';

const requests=new Map();
export const durationLabel = seconds => seconds ? `${Math.floor(Math.round(seconds)/60)}:${String(Math.round(seconds)%60).padStart(2,'0')}` : '';
export function trackSummary(index) {
  return [tracks[index]?.album,tracks[index]?.year,durationLabel(tracks[index]?.duration||musicDetails[index]?.duration)].filter(Boolean).join(' · ');
}
export async function ensureTrackDetails(index,{refresh=false}={}) {
  const detail=musicDetails[index];
  if(detail?.provider!=='deezer')return detail;
  const key=detail.catalogId;
  let record=requests.get(key);
  if(refresh||!record||record.expires<Date.now()) {
    const promise=catalogTrack(key,{refresh}).then(track=>{
      if(track.catalogId!==key)throw new Error('Faixa inválida.');
      return track;
    }).catch(error=>{if(requests.get(key)?.promise===promise)requests.delete(key);throw error;});
    record={promise,expires:Date.now()+240000};requests.set(key,record);
  }
  const track=await record.promise;
  if(requests.get(key)!==record&&requests.has(key))return ensureTrackDetails(index);
  registerTrack(track);
  window.dispatchEvent(new CustomEvent('trackmetadata',{detail:{index}}));
  return musicDetails[index];
}
