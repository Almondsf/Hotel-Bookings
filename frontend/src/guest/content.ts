/**
 * Marketing content for the public website. Kept here, apart from the
 * components, so it can be rewritten (or later moved to the CMS/back end)
 * without touching layout code.
 *
 * Photos are Unsplash placeholders; replace them with the hotel's own.
 * The testimonials are SAMPLE text for development: replace them with real
 * guest reviews (with permission) before the site goes live.
 */

const unsplash = (id: string, width = 1600) => `https://images.unsplash.com/photo-${id}?w=${width}&q=70&auto=format&fit=crop`;

export const photo = unsplash;

export const HERO_SLIDES = [
  { image: unsplash('1542314831-068cd1dbfeeb'), title: 'Your home in the heart of Lagos',
    text: 'Elegant rooms, round-the-clock power and warm Nigerian hospitality.' },
  { image: unsplash('1564501049412-61c2a3083791'), title: 'Unwind by the pool',
    text: 'Sun loungers by day, cocktails and suya by night at the Pool Bar.' },
  { image: unsplash('1571896349842-33c89424de2d'), title: 'Business or leisure, done right',
    text: 'Fast Wi-Fi, a business centre and an event hall for up to 250 guests.' },
];

export const WELCOME = {
  image: unsplash('1551882547-ff40c63fe5fa', 1000),
  kicker: 'Welcome',
  title: 'A calm retreat from the city’s rush',
  paragraphs: [
    'Minutes from the business district and the beaches, we are a home base for travellers who want comfort without fuss: quiet, spotless rooms, a kitchen that cooks Nigerian food the way you remember it, and a team that knows your name by the second morning.',
    'Stay a night for a meeting or a fortnight with the family. Either way the power stays on, the Wi-Fi stays fast and the water stays hot.',
  ],
};

export const HIGHLIGHTS = [
  { title: '24/7 power', text: 'Grid, inverter and twin generators.' },
  { title: 'Free fast Wi-Fi', text: 'Fibre broadband in every room.' },
  { title: 'Airport shuttle', text: 'Pick-up from MMIA on request.' },
  { title: 'Secure parking', text: 'Gated, guarded around the clock.' },
];

/** Mirrors the rate plans configured in the PMS; the booking engine applies the real prices and conditions. */
export const OFFERS = [
  { title: 'Bed & Breakfast', badge: 'Most popular',
    text: 'Wake up to a full Nigerian or continental breakfast for two, served in The Restaurant.' },
  { title: 'Advance Saver', badge: 'Save 15%',
    text: 'Book at least seven days ahead and pay up front to save 15% on the best available rate.' },
  { title: 'Long Stay', badge: '10% off',
    text: 'Staying five nights or more? Enjoy 10% off every night, ideal for projects and relocations.' },
  { title: 'Festive Promo', badge: 'Code DETTY25',
    text: 'Enter promo code DETTY25 when you search for an extra 8% off your December stay.' },
];

export const DINING = [
  { title: 'The Restaurant', hours: 'Breakfast 6:30–10:30 · Lunch & dinner 12:00–22:30',
    text: 'Nigerian classics and continental favourites: smoky party jollof, pounded yam and egusi, grilled croaker and a proper ribeye.',
    image: unsplash('1517248135467-4c7edcad34c4', 900) },
  { title: 'Pool Bar', hours: 'Daily 11:00 till late',
    text: 'Ice-cold Star and Guinness, signature cocktails like our Zobo Mojito, and suya platters by the water.',
    image: unsplash('1514362545857-3bc16c4c7d1b', 900) },
  { title: 'Terrace Lounge', hours: 'Daily 16:00–00:00',
    text: 'Small plates, fine wines and the evening breeze. Our favourite spot for sundowners.',
    image: unsplash('1559339352-11d035aa65de', 900) },
  { title: 'In-room dining', hours: 'Around the clock',
    text: 'A full menu delivered to your door at any hour, from pepper soup at midnight to breakfast in bed.',
    image: unsplash('1576867757603-05b134ebc379', 900) },
];

export const FACILITIES = [
  { title: 'Swimming pool', text: 'Outdoor pool with loungers and towel service, open 7am to 9pm.',
    image: unsplash('1576013551627-0cc20b96c2a7', 900) },
  { title: 'Fitness centre', text: 'Cardio machines and free weights, open around the clock for guests.',
    image: unsplash('1534438327276-14e5300c3a48', 900) },
  { title: 'Spa & massage', text: 'Deep-tissue and aromatherapy massages, by appointment.',
    image: unsplash('1544161515-4ab6ce6db874', 900) },
  { title: 'Business centre', text: 'A meeting room for 12, printing and video-conferencing.',
    image: unsplash('1431540015161-0bf868a2d407', 900) },
];

export const EVENTS = {
  image: unsplash('1519167758481-83f550bb49b3'),
  title: 'Weddings, meetings & celebrations',
  text: 'From a board meeting for ten to a wedding reception for 250, our event hall, audio-visual kit and kitchen team take care of every detail.',
};

export const TESTIMONIALS = [
  { quote: 'Spotless room, the AC worked all night and not a single power cut. The breakfast jollof alone is worth the stay.',
    name: 'Adaeze N.', from: 'Abuja · Business trip' },
  { quote: 'The staff remembered our names from day one and organised a birthday cake for my wife without us asking. We will be back.',
    name: 'Tunde & Funmi', from: 'Ibadan · Anniversary' },
  { quote: 'Fast Wi-Fi, a quiet desk and a shuttle waiting at the airport. Exactly what I need when I fly into Lagos.',
    name: 'James W.', from: 'London · Consultant' },
];

export const GALLERY = [
  '1542314831-068cd1dbfeeb', '1590490360182-c33d57733427', '1414235077428-338989a2e8c0', '1566073771259-6a8506099945',
  '1551218808-94e220e084d2', '1618773928121-c32242e63f39', '1564501049412-61c2a3083791', '1560185007-cde436f6a4d0',
].map((id) => ({ thumb: unsplash(id, 600), full: unsplash(id, 1800) }));
