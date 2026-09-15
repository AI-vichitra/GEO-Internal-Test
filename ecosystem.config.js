const path = require('path');

module.exports = {
  apps: [
    {
      name: 'geo-backend',
      cwd: path.resolve(__dirname, 'GEO-backend'),
      script: 'app.py',
      interpreter: path.resolve(__dirname, 'GEO-backend/venv/bin/python3'),
      env: {
        PORT: 8000,
        BACKEND_PORT: 8000,
        BACKEND_HOST: '0.0.0.0'
      }
    },
    {
      name: 'geo-frontend',
      cwd: path.resolve(__dirname, 'GEO-frontend'),
      script: 'node_modules/next/dist/bin/next',
      args: 'start -p 3000',
      env: {
        PORT: 3000,
        NODE_ENV: 'production'
      }
    }
  ]
};
