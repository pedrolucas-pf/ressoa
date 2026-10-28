// Verified public album art, shared with the backend; no account data or external request at login.
export async function loadLoginArtwork() {
  const response=await fetch(new URL('./assets/login-artwork.json',import.meta.url));
  if(!response.ok)throw new Error('Capas indisponíveis.');
  return response.json();
}
