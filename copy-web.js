// Copies web/ into www/ for Capacitor and the Pages deploy.
import { cpSync, rmSync, readdirSync, writeFileSync } from 'node:fs';

rmSync('www', { recursive: true, force: true });
cpSync('web', 'www', { recursive: true });
// The APK build sets VERSION_NAME, so the app can tell when a newer release is out.
if (process.env.VERSION_NAME) writeFileSync('www/version.js', `export const VERSION = ${JSON.stringify(process.env.VERSION_NAME)};\n`);
console.log('www/:', readdirSync('www').join(' '));
