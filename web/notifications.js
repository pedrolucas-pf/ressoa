import { api, getAccount, busy, mutate, updateNotifications, refreshPendingFollows } from './session.js';

export function createNotifications({ identity, followButton, toast, onFollowChange, onResponse, onComment }) {
  const button = document.getElementById('notifications-button');
  const count = document.getElementById('notification-count');
  const dialog = document.getElementById('notifications-dialog');
  const content = document.getElementById('notification-content');
  const status = document.getElementById('notification-status');
  const more = document.getElementById('notification-more');
  const retry = document.getElementById('notification-retry');
  let items = [], cursor = null, loadedVersion = -1;
  let request = null, generation = 0, reading = false, polling = false;
  let failedAppend = false;
  let checkingFollows = false;
  const processing = new Map();
  const key = item => JSON.stringify([item.kind, item.person.id, item.createdAt, item.postId || '', item.commentId || '']);
  const expired = item => item.kind !== 'request' && item.expiresAt && Date.parse(item.expiresAt) <= Date.now();

  function updateBadge() {
    const total = getAccount().notifications?.unreadCount || 0;
    count.hidden = total === 0;
    count.textContent = total > 99 ? '99+' : String(total);
    button.setAttribute('aria-label', total ? `Notificações: ${total} pendentes` : 'Notificações');
  }

  function render() {
    items = items.filter(item => !expired(item));
    content.innerHTML = items.length ? items.map(item => {
      const row = document.createElement('div');
      row.className = `person-row request-row notification-row${item.unread ? ' unread' : ''}`;
      row.dataset.notification = key(item);
      row.innerHTML = identity(item.person);
      const details = row.querySelector('.person-identity > span:last-child');
      const message = document.createElement('small');
      message.className = 'notification-message';
      message.textContent = ({request:'Quer seguir você',follow:'Começou a seguir você',like:'Curtiu seu Ressoa',repost:'Repostou seu Ressoa',comment:'Comentou no seu Ressoa'})[item.kind];
      const time = document.createElement('time');
      time.dateTime = item.createdAt;
      time.textContent = new Date(item.createdAt).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
      details.append(message, time);
      const actions = document.createElement('div');
      actions.className = 'request-actions';
      if (item.kind === 'request') {
        for (const [label, attribute, className] of [['Confirmar', 'acceptRequest', 'button'], ['Excluir', 'declineRequest', 'text-button']]) {
          const action = document.createElement('button');
          action.type = 'button'; action.className = className;
          action.textContent = label; action.dataset[attribute] = item.person.id;
          actions.append(action);
        }
      } else if (item.kind === 'follow') actions.innerHTML = followButton(item.person);
      else {
        const link=document.createElement('a');link.className='text-button';
        link.href='#ressoa/'+encodeURIComponent(item.postId);link.dataset.notificationPost=item.postId;
        if(item.kind==='comment')link.dataset.notificationComment='true';
        link.textContent=item.trackTitle||'Ver Ressoa';actions.append(link);
      }
      row.append(actions);
      const dismiss = document.createElement('button');
      dismiss.type = 'button'; dismiss.className = 'icon-button notification-dismiss';
      dismiss.textContent = '×';
      const label = item.kind === 'request' ? 'Excluir solicitação' : 'Remover notificação';
      dismiss.setAttribute('aria-label', `${label} de @${item.person.handle}`);
      dismiss.title = label;
      dismiss.dataset[item.kind === 'request' ? 'declineRequest' : 'dismissNotification'] = item.person.id;
      row.append(dismiss);
      const waiting = processing.get(key(item));
      if (waiting) {
        row.setAttribute('aria-busy', 'true');
        row.querySelectorAll('button').forEach(action => action.disabled = true);
        const action = row.querySelector(waiting === 'accept' ? '[data-accept-request]' : '.request-actions [data-decline-request]');
        if (action) action.textContent = waiting === 'accept' ? 'Confirmando…' : 'Excluindo…';
      }
      return row.outerHTML;
    }).join('') : '<p class="empty">Nenhuma notificação por enquanto.</p>';
    more.hidden = !cursor;
  }

  content.addEventListener('click', async event => {
    const postLink=event.target.closest('[data-notification-post]');
    if (postLink) { dialog.close();if(postLink.hasAttribute('data-notification-comment')){event.preventDefault();onComment?.(postLink.dataset.notificationPost);}return; }
    const control = event.target.closest('[data-accept-request], [data-decline-request], [data-dismiss-notification]');
    if (!control) return;
    event.preventDefault(); event.stopPropagation();
    const rowKey = control.closest('[data-notification]').dataset.notification;
    const item = items.find(item => key(item) === rowKey);
    if (!item || processing.has(rowKey)) return;
    const accept = control.hasAttribute('data-accept-request');
    const owner = getAccount().user.id;
    processing.set(rowKey, item.kind === 'request' ? accept ? 'accept' : 'decline' : 'dismiss');
    request?.abort(); request = null; generation++;
    content.removeAttribute('aria-busy'); more.disabled = false;
    status.textContent = ''; retry.hidden = true;
    render();
    try {
      const result = item.kind === 'request'
        ? await mutate('/api/follow-request', 'POST', { requester: item.person.id, accept, createdAt: item.createdAt, compact: true })
        : await mutate('/api/notifications', 'DELETE', { actorId: item.person.id, createdAt: item.createdAt,kind:item.kind,postId:item.postId,commentId:item.commentId });
      if (owner !== getAccount().user.id) return;
      updateNotifications(result.summary, owner);
      items = items.filter(item => key(item) !== rowKey);
      const notice = result.followResponse?.notification;
      if (notice && !items.some(item => key(item) === key(notice))) items.unshift(notice);
      if (result.followResponse) onResponse?.();
      status.textContent = ''; retry.hidden = true;
    } catch (error) {
      if (owner === getAccount().user.id) {
        toast(error.message);
        if (error.status === 404) {
          processing.delete(rowKey);
          void load();
        }
      }
    } finally {
      processing.delete(rowKey);
      if (owner === getAccount().user.id) { render(); void readVisible(); }
    }
  });

  async function readVisible() {
    if (reading || processing.size || !dialog.open) return;
    const unread = items.filter(item => item.unread).slice(0, 50);
    if (!unread.length) return;
    reading = true;
    const owner = getAccount().user.id;
    let succeeded = false;
    try {
      const { summary } = await api('/api/notifications/read', { method: 'POST', body: {
        items: unread.map(item => ({ actorId: item.person.id, createdAt: item.createdAt,kind:item.kind,postId:item.postId,commentId:item.commentId }))
      } });
      if (owner !== getAccount().user.id) return;
      updateNotifications(summary, owner);
      const read = new Set(unread.map(key));
      items.forEach(item => { if (read.has(key(item))) item.unread = false; });
      content.querySelectorAll('[data-notification]').forEach(row => {
        if (read.has(row.dataset.notification)) row.classList.remove('unread');
      });
      succeeded = true;
    } catch { /* An unread alert stays counted and can be retried on the next visit. */ }
    finally { reading = false; if (succeeded) void readVisible(); }
  }

  async function load(append = false) {
    if (!dialog.open || processing.size) return;
    request?.abort();
    request = new AbortController();
    const token = ++generation, owner = getAccount().user.id;
    const signal = request.signal;
    status.textContent = 'Carregando…';
    content.setAttribute('aria-busy', 'true');
    more.disabled = true; retry.hidden = true;
    try {
      const query = append && cursor ? `?${new URLSearchParams({ cursor })}` : '';
      const data = await api('/api/notifications' + query, { signal });
      if (token !== generation || owner !== getAccount().user.id || !dialog.open) return;
      if (append) {
        const known = new Set(items.map(key));
        items.push(...data.items.filter(item => !known.has(key(item))));
      } else items = data.items;
      cursor = data.nextCursor; loadedVersion = data.summary.version;
      updateNotifications(data.summary, owner);
      render(); status.textContent = '';
      void readVisible();
    } catch (error) {
      if (error.name !== 'AbortError' && token === generation) {
        status.textContent = error.message;
        failedAppend = append; retry.hidden = false;
      }
    } finally {
      if (token === generation) {
        request = null; more.disabled = false; content.removeAttribute('aria-busy');
      }
    }
  }

  async function poll() {
    if (document.hidden || polling || busy() || request || processing.size) return;
    polling = true;
    const owner = getAccount().user.id;
    try {
      const { summary } = await api('/api/notifications?summary=1');
      if (owner !== getAccount().user.id) return;
      updateNotifications(summary, owner);
      if (dialog.open && (loadedVersion !== getAccount().notifications.version || items.some(expired))) await load();
      else if (dialog.open) void readVisible();
    } catch { /* Keep the last confirmed counter during a temporary connection failure. */ }
    finally { polling = false; }
  }

  async function pollPendingFollows() {
    if (document.hidden || checkingFollows || busy() || !getAccount().social.requested?.length) return;
    checkingFollows = true;
    try { if (await refreshPendingFollows()) onFollowChange?.(); }
    catch { /* A failed check leaves the last confirmed follow state intact. */ }
    finally { checkingFollows = false; }
  }

  button.addEventListener('click', () => {
    dialog.showModal();
    if (processing.size) { render(); return; }
    items = []; cursor = null; content.replaceChildren(); more.hidden = true;
    void load();
  });
  dialog.addEventListener('close', () => { request?.abort(); request = null; generation++; });
  more.addEventListener('click', () => void load(true));
  retry.addEventListener('click', () => void load(failedAppend));
  window.addEventListener('accountchange', updateBadge);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { void poll(); void pollPendingFollows(); } });
  setInterval(poll, 30000);
  setInterval(pollPendingFollows, 5000);
  updateBadge();
  return { refresh: () => load() };
}
