import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HomePage } from './HomePage';

const hotel = {
  name: 'Test Hotel', address: '1 Marina, Lagos', phone: '+234 1 000 0000', email: 'stay@test.example',
  check_in_time: '14:00', check_out_time: '12:00', cancellation_policy: 'Free cancellation until 48 hours before.',
  payment_gateways: [],
};
const room = (id: number, name: string, price: string) => ({
  id, name, slug: name.toLowerCase().replace(/ /g, '-'), description: `${name} description`, base_price: price,
  max_adults: 2, max_children: 1, bed_type: 'KING', bed_count: 1, size: 300, available_room_count: 3,
  amenities: [{ id: 1, name: 'WiFi', is_premium: false }],
  images: [{ id: id, image_url: `https://images.unsplash.com/photo-${id}`, description: name }],
});

function respond(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}

describe('HomePage', () => {
  beforeEach(() => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));  // reduced motion: no slider timer
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.startsWith('/api/hotel/')) return respond(hotel);
      if (url.startsWith('/api/rooms/types/')) return respond([room(2, 'Grand Suite', '300000.00'), room(1, 'Cosy Room', '80000.00')]);
      return Promise.resolve(new Response('{}', { status: 404 }));
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  function renderPage() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter><HomePage /></MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it('lists room types cheapest first, each linking to its details page', async () => {
    renderPage();
    const titles = await screen.findAllByRole('heading', { level: 3, name: /Cosy Room|Grand Suite/ });
    expect(titles.map((t) => t.textContent)).toEqual(['Cosy Room', 'Grand Suite']);

    const card = titles[0].closest('article')!;
    expect(within(card).getByRole('link', { name: 'View details' }).getAttribute('href')).toBe('/rooms/cosy-room');
    expect(within(card).getByRole('link', { name: 'Book now' }).getAttribute('href')).toMatch(/^\/book\?check_in=/);
  });

  it('shows the hotel contact details and policies from the API', async () => {
    renderPage();
    expect((await screen.findAllByText('1 Marina, Lagos')).length).toBeGreaterThan(0);  // contact block and footer
    expect(screen.getByText('Free cancellation until 48 hours before.')).toBeTruthy();
    expect(screen.getByRole('link', { name: '+234 1 000 0000' }).getAttribute('href')).toBe('tel:+23410000000');
  });
});
