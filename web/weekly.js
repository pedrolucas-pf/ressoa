const TIME_ZONE = 'America/Sao_Paulo';
const DAY = 86400000;

export function weekKey(instant = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(instant));
  const value = type => Number(parts.find(part => part.type === type).value);
  const date = new Date(Date.UTC(value('year'), value('month') - 1, value('day')));
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}
export function nextWeekLabel(instant = new Date()) {
  const next = new Date(Date.parse(`${weekKey(instant)}T00:00:00Z`) + 7 * DAY);
  return new Intl.DateTimeFormat('pt-BR', { timeZone: 'UTC', day: '2-digit', month: '2-digit' }).format(next);
}
export function lockedForWeek(record, instant = new Date()) {
  return Boolean(record && typeof record.postId === 'string' && record.weekKey === weekKey(instant));
}
