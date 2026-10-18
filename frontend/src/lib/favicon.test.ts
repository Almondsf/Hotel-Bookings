import { describe, expect, it } from 'vitest';

import { monogramIcon, setMonogramFavicon } from './favicon';

describe('monogram favicon', () => {
  it("puts the hotel's initial in the diamond", () => {
    expect(monogramIcon('lagoon Crest Hotel')).toContain('>L</text>');
    expect(monogramIcon('   ')).toContain('>H</text>');  // no name yet
  });

  it('escapes the initial so a name can never inject markup', () => {
    expect(monogramIcon('<script>')).toContain('>&lt;</text>');
    expect(monogramIcon('& Co')).toContain('>&amp;</text>');
  });

  it('points the existing SVG icon link at the monogram', () => {
    document.head.innerHTML = '<link rel="icon" type="image/svg+xml" href="/favicon.svg">';
    setMonogramFavicon('Lagoon Crest');
    const links = document.querySelectorAll<HTMLLinkElement>('link[rel="icon"][type="image/svg+xml"]');
    expect(links).toHaveLength(1);
    expect(decodeURIComponent(links[0].href)).toContain('>L</text>');
  });
});
