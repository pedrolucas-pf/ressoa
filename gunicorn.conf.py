import os

bind = '0.0.0.0:' + os.getenv('PORT', '8000')
workers = 1
worker_class = 'gthread'
threads = 8
timeout = 60
keepalive = 5
accesslog = '-'
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s'
errorlog = '-'
# Production data lives in PostgreSQL; no account data is stored in the container.
