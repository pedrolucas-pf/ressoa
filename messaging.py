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

    def read_many(self,db,user_id,queries):
        view='''SELECT vm.* FROM dm_messages vm JOIN dm_threads vt ON vt.id=vm.thread_id
            WHERE NOT EXISTS(SELECT 1 FROM dm_hidden_messages h WHERE h.user_id=? AND h.message_id=vm.id)
            AND NOT EXISTS(SELECT 1 FROM dm_thread_clears c WHERE c.user_id=? AND c.thread_id=vm.thread_id AND (vm.created_at,vm.id)<=(c.created_at,c.message_id))
            AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=vt.user_a AND b.target_id=vt.user_b) OR (b.user_id=vt.user_b AND b.target_id=vt.user_a))
            AND (vt.user_a=? OR vt.user_b=?)'''
        prepared=[]
        for statement,parameters in queries:
            if re.search(r'\bdm_messages\b',statement,re.I):
                statement=re.sub(r'\bdm_messages\b','visible_messages',statement)
                statement=('WITH visible_messages AS ('+view+'),'+statement[5:]) if statement.startswith('WITH ') else 'WITH visible_messages AS ('+view+') '+statement
                parameters=(user_id,user_id,user_id,user_id,*parameters)
            prepared.append((statement,parameters))
        return db.fetch_many(prepared)

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
        if self.db.is_blocked(db,user_id,target):raise APIError(403,'Conversa indisponível.','blocked')
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
             WHERE (t.user_a=? OR t.user_b=?) AND m.sender_id<>? AND m.read_at IS NULL) AS unread_messages,
            (SELECT COUNT(*) FROM dm_reaction_notifications n JOIN dm_messages m ON m.id=n.message_id WHERE n.user_id=? AND n.read_at IS NULL) AS unread_reactions
            FROM users WHERE id=?''', (user_id, user_id, user_id, user_id, user_id))

    def summary(self, user_id, db=None):
        if db is None:
            with self.db.connect() as connection:
                return self.summary(user_id, connection)
        row = self.read_many(db,user_id,[self.summary_query(user_id)])[0][0]
        return self.summary_value(row)

    @staticmethod
    def summary_value(row):
        return dict(version=row['version'], unreadCount=row['unread_messages']+row['unread_reactions'])

    def inbox(self, user_id, cursor=''):
        before = self.cursor(cursor)
        restriction = 'WHERE (activity_at,thread_id)<(?,?)' if before else ''
        params = (user_id,)*8+tuple(before or ())
        with self.db.connect() as db:
            # PostgreSQL pipelines these independent reads in one network round trip.
            _, rows, summary = self.read_many(db,user_id,[
                ('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.db.is_postgres else 'BEGIN', ()),
                (f'''WITH activity AS (SELECT t.id AS thread_id,m.created_at,m.kind,m.text,m.sender_id,m.deleted_at,
                u.id,u.username,u.display_name,u.photo,
                CASE WHEN rn.created_at>m.created_at THEN rn.created_at ELSE m.created_at END AS activity_at,
                CASE WHEN rn.created_at>m.created_at THEN rn.emoji ELSE '' END AS reaction_emoji,
                (SELECT COUNT(*) FROM dm_messages n WHERE n.thread_id=t.id AND n.sender_id<>? AND n.read_at IS NULL)
                +(SELECT COUNT(*) FROM dm_reaction_notifications n JOIN dm_messages nm ON nm.id=n.message_id
                  WHERE nm.thread_id=t.id AND n.user_id=? AND n.read_at IS NULL) AS unread_count
                FROM dm_threads t JOIN users u ON u.id=CASE WHEN t.user_a=? THEN t.user_b ELSE t.user_a END
                JOIN dm_messages m ON m.id=(SELECT id FROM dm_messages WHERE thread_id=t.id ORDER BY created_at DESC,id DESC LIMIT 1)
                LEFT JOIN dm_reaction_notifications rn ON rn.user_id=? AND rn.message_id=(
                    SELECT n.message_id FROM dm_reaction_notifications n JOIN dm_messages nm ON nm.id=n.message_id
                    WHERE n.user_id=? AND n.actor_id=u.id AND nm.thread_id=t.id ORDER BY n.created_at DESC,n.message_id DESC LIMIT 1)
                WHERE (t.user_a=? OR t.user_b=?) AND u.id<>?) SELECT * FROM activity {restriction}
                ORDER BY activity_at DESC,thread_id DESC LIMIT 31''', params), self.summary_query(user_id)])
            items = [dict(person=self.db.person(row), updatedAt=row['activity_at'], unreadCount=row['unread_count'],
                          preview='Mensagem apagada' if row['deleted_at'] else 'Reagiu com '+row['reaction_emoji']+' à sua mensagem' if row['reaction_emoji'] else row['text'][:120] if row['kind'] == 'text' else 'Enviou um Ressoa',
                          sentByMe=not row['reaction_emoji'] and row['sender_id'] == user_id) for row in rows[:30]]
            next_cursor = self.encode_cursor(rows[29]['activity_at'], rows[29]['thread_id']) if len(rows) > 30 else None
            return dict(items=items, nextCursor=next_cursor,
                        summary=self.summary_value(summary[0]))

    def message(self, db, user_id, row, posts=None):
        result = dict(id=row['id'], senderId=row['sender_id'], kind=row['kind'], text=row['text'],
                      createdAt=row['created_at'], readAt=row['read_at'], post=None, unavailable=False, reactions=[], reactionNotice=None, deleted=bool(row['deleted_at']))
        if result['deleted']:return result
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
        with self.db.connect() as access:
            if self.db.is_blocked(access,user_id,target):raise APIError(403,'Conversa indisponível.','blocked')
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
            _, people, rows, summary, reaction_rows, reaction_snapshot, visible_extra = self.read_many(db,user_id,[
                ('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' if self.db.is_postgres else 'BEGIN', ()),
                ('''SELECT id,username,display_name,photo,
                    (SELECT COUNT(*) FROM dm_messages WHERE thread_id=(SELECT id FROM dm_threads WHERE user_a=? AND user_b=?) AND sender_id=? AND read_at IS NULL)
                    +(SELECT COUNT(*) FROM dm_reaction_notifications n JOIN dm_messages nm ON nm.id=n.message_id WHERE n.user_id=? AND n.actor_id=? AND n.read_at IS NULL) AS unread_count
                    FROM users WHERE id=?''', (a,b,target,user_id,target,target)),
                (f'''SELECT * FROM dm_messages WHERE thread_id=(SELECT id FROM dm_threads WHERE user_a=? AND user_b=?) {restriction}
                    ORDER BY created_at DESC,id DESC LIMIT 51''', (a, b, *(before or ()))), self.summary_query(user_id),
                (f'''SELECT r.message_id,r.user_id,r.emoji,n.created_at AS notice_created_at,n.read_at AS notice_read_at FROM dm_reactions r
                    JOIN dm_messages m ON m.id=r.message_id JOIN dm_threads t ON t.id=m.thread_id
                    LEFT JOIN dm_reaction_notifications n ON n.message_id=r.message_id AND n.user_id=?
                    WHERE t.user_a=? AND t.user_b=? AND r.user_id<>m.sender_id AND (m.id IN ({page_sql}) {extra_sql})''', (user_id,a,b,a,b,*(before or ()),*extra)),
                ('''SELECT n.created_at,n.message_id FROM dm_reaction_notifications n JOIN dm_messages m ON m.id=n.message_id
                    WHERE n.user_id=? AND n.actor_id=? AND n.read_at IS NULL AND m.thread_id=(SELECT id FROM dm_threads WHERE user_a=? AND user_b=?)
                    ORDER BY n.created_at DESC,n.message_id DESC LIMIT 1''',(user_id,target,a,b)),
                ('SELECT id FROM dm_messages WHERE thread_id=(SELECT id FROM dm_threads WHERE user_a=? AND user_b=?) AND id IN ('+(','.join('?' for _ in extra) or 'NULL')+')',(a,b,*extra))])
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
            notices = {identifier:None for identifier in extra}
            for row in reaction_rows:
                notices[row['message_id']]=row['notice_created_at'] if row['notice_read_at'] is None else None
            items = [self.message(db, user_id, row, posts) for row in reversed(rows[:50])]
            for item in items:
                item['reactions'] = reactions.get(item['id'], [])
                item['reactionNotice'] = notices.get(item['id'])
            return dict(person=self.db.person(people[0]), items=items, reactions=reactions,reactionNotices=notices,unreadCount=people[0]['unread_count'],hiddenIds=sorted(set(extra)-{row['id'] for row in visible_extra}),
                        readCursor=self.encode_cursor(rows[0]['created_at'],rows[0]['id']) if rows else None,
                        reactionReadCursor=self.encode_cursor(reaction_snapshot[0]['created_at'],reaction_snapshot[0]['message_id']) if reaction_snapshot else None,
                        nextCursor=next_cursor, summary=self.summary_value(summary[0]))

    def react(self, user_id, data):
        identifier = self.identifier(data.get('messageId'))
        emoji = data.get('emoji')
        if emoji is not None and (not isinstance(emoji,str) or emoji not in REACTION_EMOJIS):
            raise APIError(400, 'Escolha um dos emojis disponíveis.')
        with self.db.transaction() as db:
            found=self.read_many(db,user_id,[("SELECT t.user_a,t.user_b,m.sender_id FROM dm_messages m JOIN dm_threads t ON t.id=m.thread_id WHERE m.id=? AND m.deleted_at IS NULL AND (t.user_a=? OR t.user_b=?)",(identifier,user_id,user_id))])[0]
            message=found[0] if found else None
            if not message:
                raise APIError(404, 'Mensagem não encontrada.')
            if message['sender_id']==user_id:
                raise APIError(403, 'Você só pode reagir às mensagens da outra pessoa.')
            if emoji is None:
                changed = db.execute('DELETE FROM dm_reactions WHERE message_id=? AND user_id=? RETURNING message_id',(identifier,user_id)).fetchone()
            else:
                changed = db.execute('''INSERT INTO dm_reactions VALUES (?,?,?,?) ON CONFLICT(message_id,user_id)
                    DO UPDATE SET emoji=excluded.emoji,created_at=excluded.created_at
                    WHERE dm_reactions.emoji<>excluded.emoji RETURNING message_id''',(identifier,user_id,emoji,now_iso())).fetchone()
            if changed:
                db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id IN (?,?)',(message['user_a'],message['user_b']))
                if emoji is None:
                    db.execute('DELETE FROM dm_reaction_notifications WHERE user_id=? AND message_id=? AND actor_id=?',(message['sender_id'],identifier,user_id))
                else:
                    db.execute('''INSERT INTO dm_reaction_notifications VALUES (?,?,?,?,?,NULL)
                        ON CONFLICT(user_id,message_id) DO UPDATE SET actor_id=excluded.actor_id,emoji=excluded.emoji,
                        created_at=excluded.created_at,read_at=NULL''',(message['sender_id'],user_id,identifier,emoji,now_iso()))
            rows = db.execute('SELECT message_id,user_id,emoji FROM dm_reactions WHERE message_id=? AND user_id<>?',(identifier,message['sender_id'])).fetchall()
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
            db.execute('INSERT INTO dm_messages (id,thread_id,sender_id,kind,text,payload,post_id,created_at,read_at) VALUES (?,?,?,?,?,?,?,?,NULL)',
                       (identifier, thread['id'], user_id, kind, message, json.dumps(payload), post_id, timestamp))
            db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id IN (?,?)', (user_id, target))
            row = db.execute('SELECT * FROM dm_messages WHERE id=?', (identifier,)).fetchone()
            return dict(message=self.message(db, user_id, row), summary=self.summary(user_id, db))

    def read(self, user_id, data):
        ids = data.get('ids')
        if not isinstance(ids, list) or len(ids) > 50:
            raise APIError(400, 'Mensagens inválidas.')
        identifiers = list(dict.fromkeys(self.identifier(value) for value in ids))
        through=self.cursor(data.get('through'))
        reaction_through=self.cursor(data.get('reactionThrough'))
        receipts=data.get('reactionReceipts',[])
        if not isinstance(receipts,list) or len(receipts)>50:
            raise APIError(400,'Mensagens inválidas.')
        reaction_keys=[]
        for item in receipts:
            if not isinstance(item,dict):raise APIError(400,'Mensagens inválidas.')
            identifier=self.identifier(item.get('messageId'))
            timestamp=item.get('createdAt')
            try:
                if not isinstance(timestamp,str) or len(timestamp)>50 or not datetime.fromisoformat(timestamp).tzinfo:raise ValueError()
            except (ValueError,TypeError):raise APIError(400,'Mensagens inválidas.') from None
            reaction_keys.extend((identifier,timestamp))
        with self.db.transaction() as db:
            target = self.person(db, user_id, data.get('user'))['id']
            thread = self.thread(db, user_id, target)
            if thread:
                changed=[]
                if through:
                    changed+=db.execute('''UPDATE dm_messages SET read_at=? WHERE thread_id=? AND sender_id=?
                        AND read_at IS NULL AND (created_at,id)<=(?,?) RETURNING id''',(now_iso(),thread['id'],target,*through)).fetchall()
                elif identifiers:
                    marks = ','.join('?' for _ in identifiers)
                    changed+=db.execute(f'''UPDATE dm_messages SET read_at=? WHERE thread_id=?
                        AND sender_id=? AND read_at IS NULL AND id IN ({marks}) RETURNING id''',
                        (now_iso(), thread['id'], target, *identifiers)).fetchall()
                if reaction_through:
                    changed+=db.execute('''UPDATE dm_reaction_notifications SET read_at=? WHERE user_id=? AND actor_id=? AND read_at IS NULL
                        AND message_id IN (SELECT id FROM dm_messages WHERE thread_id=?) AND (created_at,message_id)<=(?,?) RETURNING message_id''',
                        (now_iso(),user_id,target,thread['id'],*reaction_through)).fetchall()
                elif reaction_keys:
                    values=','.join('(?,?)' for _ in range(len(reaction_keys)//2))
                    changed+=db.execute(f'''UPDATE dm_reaction_notifications SET read_at=? WHERE user_id=? AND actor_id=? AND read_at IS NULL
                        AND message_id IN (SELECT id FROM dm_messages WHERE thread_id=?) AND (message_id,created_at) IN (VALUES {values}) RETURNING message_id''',
                        (now_iso(),user_id,target,thread['id'],*reaction_keys)).fetchall()
                if changed:
                    db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id=?', (user_id,))
            summaries,remaining=self.read_many(db,user_id,[self.summary_query(user_id),
                ('''SELECT (SELECT COUNT(*) FROM dm_messages WHERE thread_id=? AND sender_id=? AND read_at IS NULL)
                    +(SELECT COUNT(*) FROM dm_reaction_notifications n JOIN dm_messages m ON m.id=n.message_id
                      WHERE m.thread_id=? AND n.user_id=? AND n.actor_id=? AND n.read_at IS NULL) AS unread_count''',
                    (thread['id'] if thread else '',target,thread['id'] if thread else '',user_id,target))])
            return dict(summary=self.summary_value(summaries[0]),unreadCount=remaining[0]['unread_count'])

    def delete(self,user_id,data):
        identifier=self.identifier(data.get('id'));scope=data.get('scope','me')
        if scope not in ('me','everyone'):raise APIError(400,'Opção de exclusão inválida.')
        with self.db.transaction() as db:
            row=db.execute('''SELECT m.*,t.user_a,t.user_b FROM dm_messages m JOIN dm_threads t ON t.id=m.thread_id
                WHERE m.id=? AND (t.user_a=? OR t.user_b=?)''',(identifier,user_id,user_id)).fetchone()
            if not row:raise APIError(404,'Mensagem não encontrada.')
            if scope=='everyone':
                if row['sender_id']!=user_id:raise APIError(403,'Só quem enviou pode apagar a mensagem para todos.')
                if not row['deleted_at']:
                    db.execute("UPDATE dm_messages SET kind='text',text='',payload='{}',post_id=NULL,deleted_at=?,read_at=COALESCE(read_at,?) WHERE id=?",(now_iso(),now_iso(),identifier))
                    db.execute('DELETE FROM dm_reactions WHERE message_id=?',(identifier,))
                    db.execute('DELETE FROM dm_reaction_notifications WHERE message_id=?',(identifier,))
                    db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id IN (?,?)',(row['user_a'],row['user_b']))
            elif db.execute('INSERT INTO dm_hidden_messages VALUES (?,?) ON CONFLICT DO NOTHING RETURNING message_id',(user_id,identifier)).fetchone():
                db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id=?',(user_id,))
            return dict(ok=True,id=identifier,scope=scope,summary=self.summary(user_id,db))

    def clear(self,user_id,data):
        target=self.identifier(data.get('user'))
        if target==user_id:raise APIError(400,'Conversa inválida.')
        with self.db.transaction() as db:
            thread=self.thread(db,user_id,target)
            if thread:
                latest=db.execute('SELECT created_at,id FROM dm_messages WHERE thread_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(thread['id'],)).fetchone()
                if latest:
                    db.execute('''INSERT INTO dm_thread_clears VALUES (?,?,?,?) ON CONFLICT(user_id,thread_id)
                        DO UPDATE SET created_at=excluded.created_at,message_id=excluded.message_id''',(user_id,thread['id'],latest['created_at'],latest['id']))
                    db.execute('UPDATE users SET messages_version=messages_version+1 WHERE id=?',(user_id,))
            return dict(ok=True,summary=self.summary(user_id,db))
