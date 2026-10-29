const emoji = /[\p{Extended_Pictographic}\p{Regional_Indicator}\p{Emoji_Modifier}\uFE0F\u20E3]/u;
const invisible = /[\p{C}\p{Zl}\p{Zp}]|[^\S ]/u;

export const normalizeUsername = value => typeof value === 'string'
  ? value.normalize('NFC').trim().replace(/^@+/, '').trim() : '';

export function usernameError(value) {
  const name = normalizeUsername(value);
  if (!name || [...name].length > 24) return 'Use de 1 a 24 caracteres no nome de usuário.';
  if (emoji.test(name)) return 'O nome de usuário não pode conter emojis.';
  if (invisible.test(name)) return 'Use apenas caracteres visíveis no nome de usuário.';
  return '';
}

export function bindUsernameValidation(input) {
  const validate = () => input.setCustomValidity(usernameError(input.value));
  input.addEventListener('input', validate);
  input.addEventListener('change', validate);
  input.addEventListener('blur', () => { input.value = normalizeUsername(input.value); validate(); });
  input.form?.addEventListener('reset', () => input.setCustomValidity(''));
}
