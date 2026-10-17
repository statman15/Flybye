// Copies web/ into www/ for Capacitor and the Pages deploy.
import { cpSync, rmSync, readdirSync } from 'node:fs';

rmSync('www', { recursive: true, force: true });
cpSync('web', 'www', { recursive: true });
console.log('www/:', readdirSync('www').join(' '));
