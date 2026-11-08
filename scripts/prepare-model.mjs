import { copyFile, mkdir } from 'node:fs/promises';
const source = new URL('../node_modules/@spotify/basic-pitch/', import.meta.url);
const target = new URL('../public/models/basic-pitch/', import.meta.url);
await mkdir(target, { recursive: true });
for (const file of ['model.json', 'group1-shard1of1.bin']) {
  await copyFile(new URL(`model/${file}`, source), new URL(file, target));
}
await copyFile(new URL('LICENSE', source), new URL('LICENSE', target));
console.log('Prepared local Spotify Basic Pitch model.');
