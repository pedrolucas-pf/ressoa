import { api, getAccount, busy, updateNotifications } from './session.js';

export function createNotifications({ identity, followButton }) {
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
  const key = item => JSON.stringify([item.kind, item.person.id, item.createdAt]);

  function updateBadge() {
    const total = getAccount().notifications?.unreadCount || 0;
    count.hidden = total === 0;
    count.textContent = total > 99 ? '99+' : String(total);
    button.setAttribute('aria-label', total ? `Notificações: ${total} pendentes` : 'Notificações');
  }

  function render() {
    content.innerHTML = items.length ? items.map(item => {
      const row = document.createElement('div');
      row.className = `person-row request-row notification-row${item.unread ? ' unread' : ''}`;
      row.dataset.notification = key(item);
      row.innerHTML = identity(item.person);
      const details = row.querySelector('.person-identity > span:last-child');
      const message = document.createElement('small');
      message.className = 'notification-message';
      message.textContent = item.kind === 'request' ? 'Quer seguir você' : 'Começou a seguir você';
      const time = document.createElement('time');
      time.dateTime = item.createdAt;
      time.textContent = new Date(item.createdAt).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
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
      } else actions.innerHTML = followButton(item.person);
      row.append(actions);
      return row.outerHTML;
    }).join('') : '<p class="empty">Nenhuma notificação por enquanto.</p>';
    more.hidden = !cursor;
  }

  async function readVisible() {
    if (reading || !dialog.open) return;
    const unread = items.filter(item => item.unread).slice(0, 50);
    if (!unread.length) return;
    reading = true;
    const owner = getAccount().user.id;
    let succeeded = false;
    try {
      const { summary } = await api('/api/notifications/read', { method: 'POST', body: {
        items: unread.map(item => ({ actorId: item.person.id, createdAt: item.createdAt }))
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
    if (!dialog.open) return;
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
    if (document.hidden || polling || busy() || request) return;
    polling = true;
    const owner = getAccount().user.id;
    try {
      const { summary } = await api('/api/notifications?summary=1');
      if (owner !== getAccount().user.id) return;
      updateNotifications(summary, owner);
      if (dialog.open && loadedVersion !== getAccount().notifications.version) await load();
      else if (dialog.open) void readVisible();
    } catch { /* Keep the last confirmed counter during a temporary connection failure. */ }
    finally { polling = false; }
  }

  button.addEventListener('click', () => {
    items = []; cursor = null; content.replaceChildren(); more.hidden = true;
    dialog.showModal(); void load();
  });
  dialog.addEventListener('close', () => { request?.abort(); request = null; generation++; });
  more.addEventListener('click', () => void load(true));
  retry.addEventListener('click', () => void load(failedAppend));
  window.addEventListener('accountchange', updateBadge);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void poll(); });
  setInterval(poll, 30000);
  updateBadge();
  return { refresh: () => load() };
}
