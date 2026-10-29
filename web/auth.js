import { api, setSnapshot } from './session.js';
import { loadLoginArtwork } from './login-artwork.js';
import { bindUsernameValidation } from './username.js';

const $ = selector => document.querySelector(selector);
let mode = 'login', loaded = false;
const resetMatch=location.hash.match(/^#redefinir-senha\/([A-Za-z0-9_-]{43})$/);
let resetToken=resetMatch?.[1]||'';
if(location.hash.startsWith('#redefinir-senha'))history.replaceState(null,'',location.pathname+location.search);
const labels={login:'Entrar',register:'Criar conta',forgot:'Enviar link',reset:'Salvar nova senha'};
const form = $('#auth-form');
bindUsernameValidation(form.elements.username);
function renderCovers(pool) {
  const unique=new Map();
  for(const item of pool) {
    try {
      const url=new URL(item.artwork);
      if(url.protocol==='https:'&&url.hostname.endsWith('.dzcdn.net')) unique.set(url.pathname,item);
    }catch{}
  }
  const artworks=[...unique.values()];
  for(let i=artworks.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[artworks[i],artworks[j]]=[artworks[j],artworks[i]];}
  const fragment=document.createDocumentFragment();
  for(const item of artworks.slice(0,20)) {
    const tile=document.createElement('img');
    tile.src=item.artwork;tile.alt='';tile.decoding='async';tile.draggable=false;
    fragment.append(tile);
  }
  $('#auth-covers').replaceChildren(fragment);
}
loadLoginArtwork().then(renderCovers).catch(()=>{});
document.documentElement.dataset.theme='dark';
try { localStorage.removeItem('ressoa.theme'); } catch {}
let modeAnimation;
function setMode(next, animate=true) {
  if ($('#auth-submit').disabled) return;
  const previousHeight=form.getBoundingClientRect().height;
  modeAnimation?.cancel();
  mode = next;
  $('#auth-error').textContent = '';
  $('#auth-notice').textContent = '';
  const recovering=mode==='forgot'||mode==='reset';
  $('.auth-tabs').hidden=recovering;
  $('#recovery-title').hidden=!recovering;
  $('#recovery-title').textContent=mode==='reset'?'Escolha uma nova senha':'Recuperar senha';
  $('#signup-fields').hidden = mode !== 'register';
  $('#signup-fields').disabled = mode !== 'register';
  $('#login-fields').hidden = mode !== 'login';
  $('#login-fields').disabled = mode !== 'login';
  $('#recovery-fields').hidden=mode!=='forgot';$('#recovery-fields').disabled=mode!=='forgot';
  $('#password-confirmation').hidden=mode!=='reset';$('#password-confirmation').disabled=mode!=='reset';
  $('#auth-password-field').hidden=mode==='forgot';form.elements.password.disabled=mode==='forgot';
  $('#forgot-password').hidden=mode!=='login';
  $('#back-to-login').hidden=!recovering;
  $('#remember-field').hidden=recovering;form.elements.remember.disabled=recovering;
  $('#auth-submit').textContent = labels[mode];
  form.elements.password.autocomplete = mode === 'login' ? 'current-password' : 'new-password';
  form.elements.password.minLength = mode === 'login' ? 1 : 10;
  $('#password-note').hidden = !['register','reset'].includes(mode);
  form.elements.passwordConfirmation.setCustomValidity('');
  document.querySelectorAll('[data-auth-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.authMode === mode)));
  const nextHeight=form.getBoundingClientRect().height;
  if(animate&&previousHeight&&nextHeight&&!matchMedia('(prefers-reduced-motion: reduce)').matches) {
    modeAnimation=form.animate([{height:`${previousHeight}px`,opacity:.65},{height:`${nextHeight}px`,opacity:1}],{duration:280,easing:'cubic-bezier(.2,.7,.2,1)'});
  }
}
document.querySelectorAll('[data-auth-mode]').forEach(button => button.onclick = () => setMode(button.dataset.authMode));
$('#forgot-password').onclick=()=>{setMode('forgot');form.elements.recoveryEmail.focus();};
$('#back-to-login').onclick=()=>{resetToken='';setMode('login');form.elements.identifier.focus();};
form.elements.passwordConfirmation.addEventListener('input',()=>form.elements.passwordConfirmation.setCustomValidity(''));
form.elements.password.addEventListener('input',()=>form.elements.passwordConfirmation.setCustomValidity(''));
$('#toggle-password').onclick = () => {
  const show = form.elements.password.type === 'password';
  form.elements.password.type = show ? 'text' : 'password';
  $('#toggle-password').textContent = show ? 'Ocultar' : 'Mostrar';
  $('#toggle-password').setAttribute('aria-pressed', String(show));
};
async function enter(data) {
  setSnapshot(data, true);
  if (!loaded) { await import('./app.js'); loaded = true; }
  $('#auth-screen').hidden = true;
  $('#app-shell').hidden = false;
  document.body.classList.remove('auth-open');
  window.dispatchEvent(new Event('accountentered'));
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  if(mode==='reset'&&form.elements.password.value!==form.elements.passwordConfirmation.value){form.elements.passwordConfirmation.setCustomValidity('As senhas precisam ser iguais.');form.elements.passwordConfirmation.reportValidity();return;}
  const button = $('#auth-submit'); if (button.disabled) return;
  button.disabled = true; button.textContent = ({login:'Entrando…',register:'Criando conta…',forgot:'Enviando…',reset:'Salvando…'})[mode];
  modeAnimation?.finish();
  $('#auth-error').textContent = '';
  $('#auth-notice').textContent = '';
  try {
    if(mode==='forgot'){
      const result=await api('/api/password/forgot',{method:'POST',body:{email:form.elements.recoveryEmail.value}});
      $('#auth-notice').textContent=result.message;return;
    }
    if(mode==='reset'){
      await api('/api/password/reset',{method:'POST',body:{token:resetToken,password:form.elements.password.value}});
      resetToken='';form.reset();button.disabled=false;setMode('login');
      $('#auth-notice').textContent='Senha alterada. Entre com sua nova senha.';form.elements.identifier.focus();return;
    }
    const data = Object.fromEntries(new FormData(form));
    data.remember = form.elements.remember.checked;
    const result = await api(mode === 'login' ? '/api/login' : '/api/register', { method: 'POST', body: data });
    form.reset();if(!['#pessoa/','#ressoa/'].some(prefix=>location.hash.startsWith(prefix)))location.hash='#foryou';await enter(result);
  } catch (error) { $('#auth-error').textContent = error.message; }
  finally { button.disabled = false; button.textContent = labels[mode]; }
});
window.addEventListener('sessionexpired', () => { location.replace('/?session=expired'+location.hash); });
$('#auth-retry').onclick = () => start();
window.addEventListener('hashchange',()=>{
  const match=location.hash.match(/^#redefinir-senha\/([A-Za-z0-9_-]{43})$/);
  if(!match)return;
  resetToken=match[1];history.replaceState(null,'',location.pathname+location.search);
  $('#auth-screen').hidden=false;$('#app-shell').hidden=true;document.body.classList.add('auth-open');
  $('#auth-form').hidden=false;$('#auth-loading').hidden=true;$('#auth-retry').hidden=true;
  setMode('reset',false);form.elements.password.focus();
});
async function start() {
  $('#auth-loading').hidden = false; $('#auth-retry').hidden = true; $('#auth-form').hidden = true;
  if(resetToken){setMode('reset',false);$('#auth-form').hidden=false;$('#auth-loading').hidden=true;form.elements.password.focus();return;}
  try {
    const session = await api('/api/session');
    if (session.authenticated) await enter(await api('/api/bootstrap'));
    else {
      $('#auth-form').hidden = false;
      if (new URLSearchParams(location.search).has('session')) $('#auth-error').textContent = 'Sua sessão terminou. Entre novamente.';
    }
  } catch {
    $('#auth-loading').textContent = 'Não foi possível conectar ao Ressoa.';
    $('#auth-retry').hidden = false; return;
  }
  $('#auth-loading').hidden = true;
}
setMode('login',false);
start();
