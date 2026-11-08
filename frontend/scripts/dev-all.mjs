// Starts the app and its APIs together. If a harmony server is already running
// on 8765 (for example from backend work), it is reused and left alone.
import { spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const HARMONY_PORT = 8765;

const portInUse = port => new Promise(resolve => {
  const socket = net.connect(port, '127.0.0.1');
  socket.once('connect', () => { socket.destroy(); resolve(true); });
  socket.once('error', () => resolve(false));
});

const children = [
  spawn(python, ['counter_api.py'], { stdio: 'inherit' }),
  spawn('npm', ['run', 'dev'], { stdio: 'inherit', shell: process.platform === 'win32' }),
];
if (await portInUse(HARMONY_PORT)) console.log(`Using the harmony server already running on port ${HARMONY_PORT}.`);
else children.push(spawn(python, ['-m', 'backend.harmony.playground.server', String(HARMONY_PORT)], { stdio: 'inherit', cwd: repoRoot }));

const stop = () => children.forEach(child => child.kill());
children.forEach(child => child.on('exit', code => { stop(); process.exitCode = code ?? 0; }));
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
