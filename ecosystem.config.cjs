module.exports = {
  apps: [
    {
      name: "mlplayer",
      script: "/volume1/web/MusicLoungePlayer/.venv/bin/gunicorn",
      args: "-w 2 --threads 4 --worker-class gthread -b 0.0.0.0:8680 app:app",
      cwd: "/volume1/web/MusicLoungePlayer",
      interpreter: "none",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
