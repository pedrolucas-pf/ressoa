"""Local runner. Production uses Gunicorn; see docs/DEPLOY.md."""
import argparse
import socket
from ipaddress import IPv4Address
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server
from webapp import create_app

class LocalServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = False
    allow_reuse_port = False
    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Servidor de desenvolvimento do Ressoa')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1', help='IPv4 local para previa')
    args = parser.parse_args()
    address = IPv4Address(args.host)
    if address.is_unspecified or not (address.is_private or address.is_loopback):
        parser.error('--host precisa ser um endereco IPv4 local especifico.')
    server = make_server(args.host, args.port, create_app(), server_class=LocalServer)
    visible_host = 'localhost' if address.is_loopback else args.host
    print(f'Ressoa em http://{visible_host}:{args.port} - Ctrl+C para encerrar.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
