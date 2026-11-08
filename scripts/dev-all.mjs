// Starts the Python counter-melody API and the Vite dev server together.
import { spawn } from 'node:child_process';

const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const children = [
  spawn(python, ['counter_api.py'], { stdio: 'inherit' }),
  spawn('npm', ['run', 'dev'], { stdio: 'inherit', shell: process.platform === 'win32' }),
];
const stop = () => children.forEach(child => child.kill());
children.forEach(child => child.on('exit', code => { stop(); process.exitCode = code ?? 0; }));
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
