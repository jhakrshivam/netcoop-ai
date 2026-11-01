import { cp, mkdir, rm } from 'node:fs/promises';
await rm('public', { recursive: true, force: true });
await mkdir('public', { recursive: true });
await cp('web', 'public', { recursive: true });
