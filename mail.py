"""Password recovery through Brevo's HTTPS API (no SMTP or client-side secrets)."""
import atexit
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from html import escape
from threading import BoundedSemaphore
from urllib.request import Request, urlopen

from database import APIError


class PasswordRecovery:
    def __init__(self, database):
        self.db = database
        self.key = os.getenv('BREVO_API_KEY', '').strip()
        self.sender = os.getenv('EMAIL_FROM', '').strip()
        self.name = os.getenv('EMAIL_FROM_NAME', 'Ressoa').strip()[:100]
        self.available = bool(self.key and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', self.sender))
        self.slots = BoundedSemaphore(8)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ressoa-mail')
        atexit.register(self.executor.shutdown, wait=False)

    def request(self, email, origin):
        if not self.available:
            raise APIError(503, 'A recuperação por e-mail ainda não está disponível. Tente mais tarde.')
        if not self.slots.acquire(blocking=False):
            raise APIError(503, 'Aguarde um momento e tente novamente.')
        try:
            # Every valid address follows the same queue, without revealing account existence.
            self.executor.submit(self._deliver, email, origin)
        except Exception:
            self.slots.release()
            raise APIError(503, 'Não foi possível solicitar o e-mail. Tente novamente.') from None

    def _deliver(self, email, origin):
        recovery = None
        try:
            recovery = self.db.request_password_reset(email)
            if recovery:
                self.send(recovery['email'], origin+'/#redefinir-senha/'+recovery['token'])
        except Exception:
            # Neither addresses, links nor provider responses belong in application logs.
            logging.error('Password recovery email could not be delivered. Check the email service configuration.')
            if recovery:
                try:
                    self.db.discard_password_reset(recovery['token'])
                except Exception:
                    logging.error('Could not invalidate the undelivered password recovery link.')
        finally:
            self.slots.release()

    def send(self, recipient, link):
        safe_link = escape(link, quote=True)
        content = dict(sender=dict(name=self.name, email=self.sender), to=[dict(email=recipient)],
            subject='Redefina sua senha do Ressoa',
            textContent=f'Redefina sua senha do Ressoa\n\n{link}\n\nO link vale por 30 minutos e pode ser usado uma vez. Se não pediu a alteração, ignore este e-mail. Sua senha continua a mesma.',
            htmlContent=f'''<!doctype html><html lang="pt-BR"><body style="background:#101010;color:#f4f0e9;font-family:Arial,sans-serif;padding:32px">
                <div style="max-width:480px;margin:auto"><h1 style="font-size:30px">ressoa</h1><h2 style="font-size:22px">Redefinir senha</h2>
                <p>Recebemos um pedido para alterar sua senha.</p><p style="margin:30px 0"><a href="{safe_link}" style="background:#f4f0e9;color:#101010;padding:14px 22px;text-decoration:none;border-radius:4px">Escolher nova senha</a></p>
                <p>O link vale por 30 minutos e pode ser usado uma vez.</p><p>Se não pediu a alteração, ignore este e-mail. Sua senha continua a mesma.</p>
                <p style="font-size:12px;overflow-wrap:anywhere">Se o botão não abrir, copie este endereço:<br><a href="{safe_link}" style="color:#f4f0e9">{safe_link}</a></p></div></body></html>''')
        request = Request('https://api.brevo.com/v3/smtp/email', data=json.dumps(content).encode('utf-8'),
            headers={'api-key':self.key, 'Content-Type':'application/json', 'Accept':'application/json', 'User-Agent':'Ressoa'}, method='POST')
        with urlopen(request, timeout=12) as response:
            if response.status not in (200,201,202):
                raise RuntimeError('Email was not accepted.')
