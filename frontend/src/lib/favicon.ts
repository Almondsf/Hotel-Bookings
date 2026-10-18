/**
 * The browser-tab icon: the site's gold diamond monogram on a dark tile, with
 * the hotel's initial inside, so the tab matches the logo in the header.
 * public/favicon.svg is the letterless version used until the hotel's name
 * loads (and by the staff portal).
 */
const escapeXml = (text: string) =>
  text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[c]!);

export function monogramIcon(initial: string) {
  const letter = escapeXml(initial.trim().charAt(0).toUpperCase() || 'H');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#1d1a17"/>
  <rect x="13.5" y="13.5" width="37" height="37" fill="none" stroke="#c9a46a" stroke-width="3.5" transform="rotate(45 32 32)"/>
  <text x="32" y="42.5" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif" font-size="29"
        font-weight="700" fill="#c9a46a">${letter}</text>
</svg>`;
}

/** Point the tab icon at the monogram for `name` (the hotel's name). */
export function setMonogramFavicon(name: string) {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"][type="image/svg+xml"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    document.head.appendChild(link);
  }
  link.href = `data:image/svg+xml,${encodeURIComponent(monogramIcon(name))}`;
}
