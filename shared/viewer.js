'use strict';

// The key stays in the URL fragment. Only the encrypted document is requested.
(async () => {
  const status = document.getElementById('status');
  const encodedKey = location.hash.slice(1);
  if (!/^[A-Za-z0-9_-]{43}$/.test(encodedKey)) {
    status.textContent = 'Open the complete link Will shared with you.';
    return;
  }

  let objectUrl;
  try {
    const rawKey = Uint8Array.from(
      atob(encodedKey.replace(/-/g, '+').replace(/_/g, '/') + '='),
      character => character.charCodeAt(0)
    );
    const key = await crypto.subtle.importKey('raw', rawKey, 'AES-GCM', false, ['decrypt']);
    const response = await fetch('document.bin', { credentials: 'omit', referrerPolicy: 'no-referrer' });
    if (!response.ok) throw new Error('Document unavailable');
    const encrypted = new Uint8Array(await response.arrayBuffer());
    if (encrypted.length < 29) throw new Error('Incomplete document');
    const plaintext = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: encrypted.slice(0, 12), tagLength: 128 },
      key,
      encrypted.slice(12)
    );
    const signature = new TextDecoder().decode(new Uint8Array(plaintext, 0, 5));
    if (signature !== '%PDF-') throw new Error('Unexpected document');

    objectUrl = URL.createObjectURL(new Blob([plaintext], { type: 'application/pdf' }));
    document.getElementById('open').href = objectUrl;
    document.getElementById('download').href = objectUrl;
    document.querySelector('nav').hidden = false;
    const viewer = document.getElementById('document');
    viewer.src = objectUrl;
    viewer.hidden = false;
    status.hidden = true;
  } catch {
    status.textContent = 'The document could not be opened. Check that you have the complete link, then reload this page.';
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
})();

window.addEventListener('hashchange', () => location.reload());
