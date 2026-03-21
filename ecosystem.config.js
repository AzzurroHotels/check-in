module.exports = {
  apps: [{
    name: 'check-in',
    cwd: '/var/www/check-in',
    script: './venv/bin/gunicorn',
    args: '--workers 3 --bind localhost:5005 app:app',
    autorestart: true,
    watch: false,
  }]
};
