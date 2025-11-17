# Gunicorn configuration for Render deployment
# Purpose: Handle long-running /api/fetch-news endpoint (2-5 minutes)

import os
import multiprocessing

# Worker timeout - set to 10 minutes (600 seconds)
# /api/fetch-news takes 2-5 minutes, so we need a long timeout
timeout = 600

# Keep-alive timeout
keepalive = 5

# Number of worker processes
# Using 1 worker to minimize memory usage on Render free tier (512MB)
workers = 1

# Worker class
worker_class = 'sync'

# Maximum requests per worker before restart (disabled to preserve cache)
# max_requests = 100
# max_requests_jitter = 10

# Bind address - use Render's PORT or default to 5000
port = os.environ.get('PORT', '5000')
bind = f'0.0.0.0:{port}'

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Graceful timeout for worker shutdown
graceful_timeout = 30

# Preload app (not recommended for memory-sensitive apps)
preload_app = False
