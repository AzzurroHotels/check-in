module.exports = {
  apps: [{
    name: 'check-in',
    cwd: '/var/www/check-in',
    interpreter: './venv/bin/python3',
    script: './venv/bin/gunicorn',
    args: '--workers 3 --bind localhost:5005 app:app',
    autorestart: true,
    watch: false,
  }]
};
