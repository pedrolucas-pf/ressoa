"""One-to-one conversations. Private messages never become diary or feed posts."""
import base64
import json
import re
import uuid
from datetime import datetime
from database import APIError, clean_track, now_iso, text

REACTION_EMOJIS = ('❤️','👍','😂','😮','🔥','🥲','😍','🥰','😊','😁','😎','🤩','😭','😢','😅','🤣','🤔','👀',
                   '🙌','👏','🤝','💪','🙏','👌','💯','✨','🎉','🎵','🎶','🎧','💿','🖤','💜','💙','🤍','💔','🫶')


class Messaging:
    def __init__(self, database):
        self.db = database

    @staticmethod
    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
            raise APIError(400, 'Mensagem inválida.')
        return value

    @staticmethod
    def cursor(value):
        if not value:
            return None
        try:
            if not isinstance(value, str) or len(value) > 400 or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
                raise ValueError()
            parts = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
            if not isinstance(parts, list) or len(parts) != 2 or any(not isinstance(v, str) for v in parts):
                raise ValueError()
            if len(parts[0]) > 50 or not datetime.fromisoformat(parts[0]).tzinfo:
                raise ValueError()
            Messaging.identifier(parts[1])
            return tuple(parts)
        except (ValueError, TypeError, UnicodeError):
            raise APIError(400, 'Reabra a conversa para atualizar as mensagens.') from None

    @staticmethod
    def encode_cursor(timestamp, identifier):
        return base64.urlsafe_b64encode(json.dumps([timestamp, identifier]).encode()).decode().rstrip('=')

    def person(self, db, user_id, target):
        target = self.identifier(target)
        row = db.execute('SELECT id,username,display_name,photo FROM users WHERE id=?', (target,)).fetchone()
        if not row or target == user_id:
            raise APIError(404, 'Escolha outra pessoa para conversar.')
        return self.db.person(row)

    @staticmethod
    def thread(db, user_id, target):
        a, b = sorted((user_id, target))
        return db.execute('SELECT id FROM dm_threads WHERE user_a=? AND user_b=?', (a, b)).fetchone()

    @staticmethod
    def summary_query(user_id):
        return ('''SELECT messages_version AS version,
            (SELECT COUNT(*) FROM dm_messages m JOIN dm_threads t ON t.id=m.thread_id
             WHERE (t.user_a=? OR t.user_b=?) AND m.sender_id<>? AND m.read_at IS NULL) AS unread_count
            FROM users WHERE id=?''', (user_id, user_id, user_id, user_id))

    def summary(self, user_id, db=None):
        if db is None:
            with self.db.connect() as connection:
                return self.summary(user_id, connection)
        row = db.execute(*self.summary_query(user_id)).fetchone()
        return dict(version=row['version'], unreadCount=row['unread_count'])

    def inbox(self, user_id, cursor=''):
        before = self.cursor(cursor)
        restriction = ' AND (m.created_at,t.id)<(?,?)' if before else ''
        params = (user_id, user_id, user_id, user_id, user_id, *(before or ()))
        with self.db.connect() as db:
            # PostgreSQL pipelines these independent reads in one network round trip.
            _, rows, summary = db.fetch_many([
                ('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.db.is_postgres else 'BEGIN', ()),
                (f'''SELECT t.id AS thread_id,m.created_at,m.kind,m.text,m.sender_id,
                u.id,u.username,u.display_name,u.photo,
                (SELECT COUNT(*) FROM dm_messages n WHERE n.thread_id=t.id AND n.sender_id<>? AND n.read_at IS NULL) AS unread_count
                FROM dm_threads t JOIN users u ON u.id=CASE WHEN t.user_a=? THEN t.user_b ELSE t.user_a END
                JOIN dm_messages m ON m.id=(SELECT id FROM dm_messages WHERE thread_id=t.id ORDER BY created_at DESC,id DESC LIMIT 1)
                WHERE (t.user_a=? OR t.user_b=?) AND u.id<>? {restriction}
                ORDER BY m.created_at DESC,t.id DESC LIMIT 31''', params), self.summary_query(user_id)])
            items = [dict(person=self.db.person(row), updatedAt=row['created_at'], unreadCount=row['unread_count'],
                          preview=row['text'][:120] if row['kind'] == 'text' else 'Enviou um Ressoa',
                          sentByMe=row['sender_id'] == user_id) for row in rows[:30]]
            next_cursor = self.encode_cursor(rows[29]['created_at'], rows[29]['thread_id']) if len(rows) > 30 else None
            return dict(items=items, nextCursor=next_cursor,
                        summary=dict(version=summary[0]['version'], unreadCount=summary[0]['unread_count']))

    def message(self, db, user_id, row, posts=None):
        result = dict(id=row['id'], senderId=row['sender_id'], kind=row['kind'], text=row['text'],
                      createdAt=row['created_at'], readAt=row['read_at'], post=None, unavailable=False, reactions=[])
        if row['kind'] == 'ressoa':
            result['post'] = dict(json.loads(row['payload']), id=row['id'], ownerId=row['sender_id'], kind='direct', visibility='direct')
        elif row['kind'] == 'post':
            if posts is not None:
                result['post'] = posts.get(row['post_id'])
                result['unavailable'] = result['post'] is None
                return result
            try:
                if not row['post_id']:
                    raise APIError(404, 'Ressoa indisponível.')
                post = self.db.accessible(db, user_id, row['post_id'])
                result['post'] = self.db.post(db, post)
            except APIError as error:
                if error.status not in (403, 404):
                    raise
                result['unavailable'] = True
        return result

    @staticmethod
    def group_reactions(rows, user_id):
        grouped = {}
        for row in rows:
            reactions = grouped.setdefault(row['message_id'], {})
            reaction = reactions.setdefault(row['emoji'], dict(emoji=row['emoji'], count=0, mine=False))
            reaction['count'] += 1
            reaction['mine'] = reaction['mine'] or row['user_id'] == user_id
        return {identifier: sorted(values.values(), key=lambda item:item['emoji']) for identifier,values in grouped.items()}

    def conversation(self, user_id, target, cursor='', reaction_ids=''):
        before = self.cursor(cursor)
        target = self.identifier(target)
        if target == user_id:
            raise APIError(404, 'Escolha outra pessoa para conversar.')
        a, b = sorted((user_id, target))
        restriction = ' AND (created_at,id)<(?,?)' if before else ''
        if not isinstance(reaction_ids,str) or len(reaction_ids)>5050 or len(reaction_ids.split(','))>50:
            raise APIError(400, 'Mensagens inválidas.')
        extra = tuple(dict.fromkeys(self.identifier(value) for value in reaction_ids.split(',') if value))
        extra_sql = ' OR m.id IN ('+','.join('?' for _ in extra)+')' if extra else ''
        page_sql = f'SELECT id FROM dm_messages WHERE thread_id=(SELECT id FROM dm_threads WHERE user_a=? AND user_b=?) {restriction} ORDER BY created_at DESC,id DESC LIMIT 50'
        with self.db.connect() as db:
            _, people, rows, summary, reaction_rows = db.fetch_many([
                ('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.db.is_postgres else 'BEGIN', ()),
                ('SELECT id,username,display_name,photo FROM users WHERE id=?', (target,)),
                (f'''SELECT * FROM dm_messages WHERE thread_id=(SELECT id FROM dm_threads WHERE user_a=? AND user_b=?) {restriction}
                    ORDER BY created_at DESC,id DESC LIMIT 51''', (a, b, *(before or ()))), self.summary_query(user_id),
                (f'''SELECT r.message_id,r.user_id,r.emoji FROM dm_reactions r
                    JOIN dm_messages m ON m.id=r.message_id JOIN dm_threads t ON t.id=m.thread_id
                    WHERE t.user_a=? AND t.user_b=? AND (m.id IN ({page_sql}) {extra_sql})''', (a,b,a,b,*(before or ()),*extra))])
            if not people:
                raise APIError(404, 'Escolha outra pessoa para conversar.')
            # Shared posts are reauthorized together, including expired weekly choices.
            identifiers = tuple({row['post_id'] for row in rows[:50] if row['kind'] == 'post' and row['post_id']})
            posts = {}
            if identifiers:
                for post in db.execute(*self.db.accessible_query(user_id, identifiers)).fetchall():
                    if post['kind'] == 'weekly' and not post['active_week']:
                        continue
                    self.db.cache_accessible(db, post)
                    posts[post['id']] = self.db.post(db, post)
            next_cursor = self.encode_cursor(rows[49]['created_at'], rows[49]['id']) if len(rows) > 50 else None
            reactions = {identifier:[] for identifier in extra}
            reactions.update(self.group_reactions(reaction_rows, user_id))
            items = [self.message(db, user_id, row, posts) for row in reversed(rows[:50])]
            for item in items:
                item['reactions'] = reactions.get(item['id'], [])
            return dict(person=self.db.person(people[0]), items=items, reactions=reactions,
                        nextCursor=next_cursor, summary=dict(version=summary[0]['version'], unreadCount=summary[0]['unread_count']))

    def react(self, user_id, data):
        identifier = self.identifier(data.get('messageId'))
        emoji = data.get('emoji')
        if emoji is not None and (not isinstance(emoji,str) or emoji not in REACTION_EMOJIS):
            raise APIError(400, 'Escolha um dos emojis disponíveis.')
        with self.db.transaction() as db:
            message = db.execute('''SELECT t.user_a,t.user_b FROM dm_messages m JOIN dm_threads t ON t.id=m.thread_id
                WHERE m.id=? AND (t.user_a=? OR t.user_b=?)''',(identifier,user_id,user_id)).fetchone()
            if not message:
                raise APIError(404, 'Mensagem não encontrada.')
            if emoji is None:
                changed = db.execute('DELETE FROM dm_reactions WHERE message_id=? AND user_id=? RETURNING message_id',(identifier,user_id)).fetchone()
            else:
                changed = db.execute('''INSERT INTO dm_reactions VALUES (?,?,?,?) ON CONFLICT(message_id,user_id)
                    DO UPDATE SET emoji=excluded.emoji,created_at=excluded.created_at
                    WHERE dm_reactions.emoji<>excluded.emoji RETURNING message_id''',(identifier,user_id,emoji,now_iso())).fetchone()
            if changed:
                db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id IN (?,?)',(message['user_a'],message['user_b']))
            rows = db.execute('SELECT message_id,user_id,emoji FROM dm_reactions WHERE message_id=?',(identifier,)).fetchall()
            return dict(messageId=identifier, reactions=self.group_reactions(rows,user_id).get(identifier,[]), summary=self.summary(user_id,db))

    def ressoa_payload(self, value):
        if not isinstance(value, dict):
            raise APIError(400, 'Selecione uma música para o Ressoa.')
        track = clean_track(value.get('track'))
        audio = self.db.clean_audio_excerpt(value.get('audioExcerpt'), track)
        if audio and track['provider'] != 'deezer' and audio.get('source') != 'spotify':
            raise APIError(400, 'Escolha uma prévia ou um trecho do Spotify conectado.')
        return dict(track=track, text=text(value.get('text', ''), 0, 2400),
                    lyricExcerpt=self.db.clean_excerpt(value.get('lyricExcerpt', '')), audioExcerpt=audio)

    def send(self, user_id, data):
        identifier = self.identifier(data.get('id'))
        target = self.identifier(data.get('user'))
        kind = data.get('kind', 'text')
        if kind not in ('text', 'ressoa', 'post'):
            raise APIError(400, 'Tipo de mensagem inválido.')
        with self.db.transaction() as db:
            self.person(db, user_id, target)
            previous = db.execute('''SELECT m.*,t.user_a,t.user_b FROM dm_messages m
                JOIN dm_threads t ON t.id=m.thread_id WHERE m.id=?''', (identifier,)).fetchone()
            if previous:
                if previous['sender_id'] != user_id or target not in (previous['user_a'], previous['user_b']):
                    raise APIError(409, 'Essa mensagem já foi utilizada. Tente novamente.')
                return dict(message=self.message(db, user_id, previous), summary=self.summary(user_id, db))
            message, payload, post_id = '', {}, None
            if kind == 'text':
                message = text(data.get('text'), 1, 2400)
            elif kind == 'ressoa':
                payload = self.ressoa_payload(data.get('post'))
            else:
                post_id = self.identifier(data.get('postId'))
                post = self.db.accessible(db, user_id, post_id)
                if post['visibility'] == 'private' and post['owner_id'] == user_id:
                    payload = self.ressoa_payload(self.db.post(db, post))
                    kind, post_id = 'ressoa', None
                else:
                    try:
                        self.db.accessible(db, target, post_id)
                    except APIError:
                        raise APIError(403, 'Essa pessoa não tem permissão para ver este Ressoa.') from None
            thread = self.thread(db, user_id, target)
            timestamp = now_iso()
            if not thread:
                a, b = sorted((user_id, target))
                db.execute('INSERT INTO dm_threads VALUES (?,?,?,?) ON CONFLICT(user_a,user_b) DO NOTHING',
                           (str(uuid.uuid4()), a, b, timestamp))
                thread = self.thread(db, user_id, target)
            db.execute('INSERT INTO dm_messages VALUES (?,?,?,?,?,?,?,?,NULL)',
                       (identifier, thread['id'], user_id, kind, message, json.dumps(payload), post_id, timestamp))
            db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id IN (?,?)', (user_id, target))
            row = db.execute('SELECT * FROM dm_messages WHERE id=?', (identifier,)).fetchone()
            return dict(message=self.message(db, user_id, row), summary=self.summary(user_id, db))

    def read(self, user_id, data):
        ids = data.get('ids')
        if not isinstance(ids, list) or len(ids) > 50:
            raise APIError(400, 'Mensagens inválidas.')
        identifiers = list(dict.fromkeys(self.identifier(value) for value in ids))
        with self.db.transaction() as db:
            target = self.person(db, user_id, data.get('user'))['id']
            thread = self.thread(db, user_id, target)
            if thread and identifiers:
                marks = ','.join('?' for _ in identifiers)
                changed = db.execute(f'''UPDATE dm_messages SET read_at=? WHERE thread_id=?
                    AND sender_id=? AND read_at IS NULL AND id IN ({marks}) RETURNING id''',
                    (now_iso(), thread['id'], target, *identifiers)).fetchall()
                if changed:
                    db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id=?', (user_id,))
            return dict(summary=self.summary(user_id, db))
