// Renders the app icon (one SVG, 108x108 like an Android adaptive icon) to every PNG the web app and the APK use.
// Run: node tools/make-icons.mjs   (needs Chrome, like the smoke test)
import { existsSync } from 'node:fs';
import puppeteer from 'puppeteer-core';

// Sky, a low sun, and a white plane climbing away from it. Everything that matters sits in the central 66 (the adaptive-icon safe zone).
const PLANE = 'M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z'; // Material "flight", Apache 2.0
const svg = (viewBox, clip = '') => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" width="100%" height="100%">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0a4fa8"/><stop offset=".55" stop-color="#2a8ce4"/><stop offset=".8" stop-color="#8ccaf5"/><stop offset="1" stop-color="#ffd9a6"/></linearGradient>
    ${clip}
  </defs>
  <g ${clip ? 'clip-path="url(#c)"' : ''}>
    <rect width="108" height="108" fill="url(#sky)"/>
    <circle cx="75" cy="77" r="15" fill="#fff4cc" fill-opacity=".5"/>
    <circle cx="75" cy="77" r="10.5" fill="#ffc23d"/>
    <path d="M27 81 Q 37 76 41 64" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="2.4" stroke-linecap="round" stroke-dasharray="1 5"/>
    <path d="${PLANE}" fill="#fff" transform="translate(52 48) rotate(45) scale(1.55) translate(-12 -12)"/>
  </g>
</svg>`;
const FULL = '0 0 108 108', VISIBLE = '18 18 72 72', MASKABLE = '14 14 80 80';
const rounded = `<clipPath id="c"><rect x="18" y="18" width="72" height="72" rx="14"/></clipPath>`;
const round = `<clipPath id="c"><circle cx="54" cy="54" r="36"/></clipPath>`;

const out = [
  ['web/icon-192.png', 192, svg(MASKABLE)], ['web/icon-512.png', 512, svg(MASKABLE)], ['web/apple-touch-icon.png', 180, svg(MASKABLE)],
];
const res = 'android/app/src/main/res';
for (const [d, k] of Object.entries({ mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 })) {
  out.push([`${res}/mipmap-${d}/ic_launcher_foreground.png`, 108 * k, svg(FULL)],
    [`${res}/mipmap-${d}/ic_launcher.png`, 48 * k, svg(VISIBLE, rounded)],
    [`${res}/mipmap-${d}/ic_launcher_round.png`, 48 * k, svg(VISIBLE, round)]);
}

const chrome = [process.env.CHROME_PATH, 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', '/usr/bin/google-chrome'].find(p => p && existsSync(p));
const browser = await puppeteer.launch({ executablePath: chrome });
const page = await browser.newPage();
for (const [file, size, markup] of out) {
  await page.setViewport({ width: size, height: size });
  await page.setContent(`<style>html,body{margin:0;background:transparent}</style>${markup}`);
  await page.screenshot({ path: file, omitBackground: true });
}
await browser.close();
console.log(`${out.length} icons written`);
