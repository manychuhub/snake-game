import sqlite3,json, re, math, os
from datetime import datetime,timezone
from contextlib import contextmanager,closing
from config import DATA
class Memory:
    def __init__(self,path=None):
        self.dsn = os.getenv('SHIFT_BRIDGE_ENGINE_DATABASE_URL') if path is None else None
        if self.dsn:
            import postgres_store
            postgres_store.verify(self.dsn, engine=True)
            return
        self.path=path or DATA/'bridge.db'; self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, created TEXT NOT NULL, body TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, embedding TEXT, embed_model TEXT);
            CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, created TEXT NOT NULL, body TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, created TEXT NOT NULL, name TEXT NOT NULL, page INTEGER, text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, created TEXT NOT NULL, task TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, thinking_tokens INTEGER, total_tokens INTEGER);''')
    @contextmanager
    def db(self):
        if self.dsn:
            import postgres_store
            with postgres_store.database(self.dsn, engine=True) as connection:
                yield connection
            return
        with closing(sqlite3.connect(self.path,timeout=10)) as c:
            c.row_factory=sqlite3.Row
            with c: yield c
    def add(self,body,approved=False):
        with self.db() as c: return c.execute('INSERT INTO records(created,body,approved) VALUES(?,?,?) RETURNING id',(now(),json.dumps(body,ensure_ascii=False),int(approved))).fetchone()[0]
    def update(self,id,body=None,approve=False):
        with self.db() as c:
            old=c.execute('SELECT * FROM records WHERE id=?',(id,)).fetchone()
            if not old: raise KeyError(id)
            c.execute('UPDATE records SET body=?, approved=?, embedding=NULL, embed_model=NULL WHERE id=?',(json.dumps(body,ensure_ascii=False) if body is not None else old['body'],int(approve),id))
    def rows(self,approved=True):
        with self.db() as c: rows=c.execute('SELECT * FROM records '+('WHERE approved=1 ' if approved else '')+'ORDER BY id DESC').fetchall()
        return [{'id':r['id'],'created':r['created'],'approved':bool(r['approved']),**json.loads(r['body'])} for r in rows]
    def get(self,id):
        return next((r for r in self.rows(False) if r['id']==id),None)
    def docs(self):
        with self.db() as c: return [dict(r) for r in c.execute('SELECT * FROM documents ORDER BY id DESC')]
    def add_doc(self,name,page,text):
        with self.db() as c: return c.execute('INSERT INTO documents(created,name,page,text) VALUES(?,?,?,?) RETURNING id',(now(),name,page,text)).fetchone()[0]
    def report(self,body):
        with self.db() as c: return c.execute('INSERT INTO reports(created,body) VALUES(?,?) RETURNING id',(now(),json.dumps(body,ensure_ascii=False))).fetchone()[0]
    def approve_report(self,id,text=None):
        with self.db() as c:
            r=c.execute('SELECT body FROM reports WHERE id=?',(id,)).fetchone()
            if not r: raise KeyError(id)
            b=json.loads(r['body']); b['content']=text if text is not None else b['content']; c.execute('UPDATE reports SET body=?,approved=1 WHERE id=?',(json.dumps(b,ensure_ascii=False),id))
    def reports(self):
        with self.db() as c: return [dict(id=r['id'],created=r['created'],approved=bool(r['approved']),**json.loads(r['body'])) for r in c.execute('SELECT * FROM reports ORDER BY id DESC')]
    def vectors(self):
        with self.db() as c: return [dict(r) for r in c.execute('SELECT id,embedding,embed_model FROM records WHERE approved=1 AND embedding IS NOT NULL')]
    def set_vector(self,id,model,vector,body):
        with self.db() as c: return c.execute('UPDATE records SET embedding=?,embed_model=? WHERE id=? AND approved=1 AND body=?',(json.dumps(vector),model,id,body)).rowcount
    def index_rows(self):
        with self.db() as c: return [dict(r) for r in c.execute('SELECT id,body FROM records WHERE approved=1')]
    def log(self,task,usages):
        with self.db() as c: c.executemany('INSERT INTO usage(created,task,model,input_tokens,output_tokens,thinking_tokens,total_tokens) VALUES(?,?,?,?,?,?,?)',[(now(),task,u['model'],u['input_tokens'],u['output_tokens'],u['thinking_tokens'],u['total_tokens']) for u in usages])
    def usage(self):
        with self.db() as c: return [dict(r) for r in c.execute('SELECT model,COUNT(*) AS calls,SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,SUM(thinking_tokens) AS thinking_tokens,SUM(total_tokens) AS total_tokens FROM usage GROUP BY model')]
    def search(self,query,limit=12,vector=None,model=None):
        words=set(re.findall(r'[\w-]+',query.lower())); grams={w[i:i+2] for w in words for i in range(len(w)-1)}
        vectors={r['id']:json.loads(r['embedding']) for r in self.vectors() if r['embed_model']==model} if vector else {}
        def score(text):
            t=text.lower(); return sum(2 for w in words if w in t)+.15*sum(g in t for g in grams)
        def cosine(a,b):
            if len(a)!=len(b): return 0
            return sum(x*y for x,y in zip(a,b))/(math.sqrt(sum(x*x for x in a)*sum(y*y for y in b)) or 1)
        hits=[]
        for r in self.rows():
            s=score(json.dumps(r,ensure_ascii=False))
            if r['id'] in vectors: s+=max(0,cosine(vector,vectors[r['id']])-.50)*10
            if s>0: hits.append((s,{'source':f'R{r["id"]}',**r}))
        for d in self.docs():
            s=score(d['name']+' '+d['text']);
            if s>0: hits.append((s,{'source':f'D{d["id"]}',**d}))
        return [r for _,r in sorted(hits,key=lambda x:x[0],reverse=True)[:limit]]
def now(): return datetime.now(timezone.utc).isoformat()
