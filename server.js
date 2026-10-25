const { spawn } = require('node:child_process');
const child = spawn(process.env.PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3'), ['backend.py'], { cwd: __dirname, stdio: 'inherit', env: process.env });
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code || 0; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
