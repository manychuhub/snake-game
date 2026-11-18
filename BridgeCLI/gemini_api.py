import httpx, re, json, time, ssl, socket
from config import KEY, MODEL, EMBED_MODEL, TIMEOUT
BASE='https://generativelanguage.googleapis.com/v1beta'
class GeminiError(Exception): pass

def network_error(exc, path):
    # Never include raw exception strings, headers, or secrets in responses.
    stage = '모델 목록 조회' if path.startswith('/models?') else ('임베딩' if ':embedContent' in path else 'AI 응답 생성')
    causes=[]; pending=[exc]; seen=set()
    while pending:
        current=pending.pop()
        if id(current) in seen: continue
        seen.add(id(current)); causes.append(current)
        for child in (current.__cause__, current.__context__):
            if child is not None: pending.append(child)
    if any(isinstance(x, ssl.SSLCertVerificationError) for x in causes) or any('certificate_verify_failed' in str(x).lower() or 'certificate verify failed' in str(x).lower() for x in causes):
        reason='SSL 인증서 검증 실패 (Windows 인증서 또는 네트워크 프록시 확인)'
    elif any(isinstance(x, socket.gaierror) for x in causes):
        reason='DNS 이름 조회 실패'
    elif isinstance(exc,httpx.ProxyError): reason='프록시 연결 실패'
    elif isinstance(exc,httpx.ConnectTimeout): reason='Google 서버 연결 시간 초과 (15초)'
    elif isinstance(exc,httpx.ReadTimeout): reason=f'Google 응답 읽기 시간 초과 ({TIMEOUT}초)'
    elif isinstance(exc,httpx.WriteTimeout): reason=f'Google 요청 전송 시간 초과 ({TIMEOUT}초)'
    elif isinstance(exc,httpx.PoolTimeout): reason='HTTP 연결 대기 시간 초과'
    elif isinstance(exc,httpx.ConnectError): reason='Google 서버 연결 실패 (네트워크 또는 TLS 확인)'
    elif isinstance(exc,httpx.RemoteProtocolError): reason='Google 또는 프록시가 응답 연결을 중단함'
    else: reason='HTTP 네트워크 통신 오류'
    return f'{stage}: {reason} [{type(exc).__name__}]'

class Gemini:
    def __init__(self,key=KEY,model=MODEL,embed_model=EMBED_MODEL):
        self.key=key; self.model=model; self.embed_model=embed_model
        self.usage=[]
    async def request(self,method,path,body=None):
        if not self.key: raise GeminiError('GEMINI_API_KEY를 .env에 설정하세요.')
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT,connect=15.0),follow_redirects=False) as c:
                r=await c.request(method,BASE+path,headers={'x-goog-api-key':self.key},json=body)
        except httpx.HTTPError as e: raise GeminiError(network_error(e,path)) from None
        if r.status_code>=300:
            hints={400:'요청 또는 모델 설정 확인',401:'API 키 확인',403:'API 키 권한 및 프로젝트 확인',404:'모델 지원 여부 확인',429:'할당량 또는 결제 설정 확인',503:'Google 서비스 일시 오류'}
            raise GeminiError(f'Google API HTTP {r.status_code}: '+hints.get(r.status_code,'서비스 오류'))
        try: return r.json()
        except ValueError: raise GeminiError('Google API 응답 형식 오류') from None
    async def models(self):
        out=[]; page=''
        for _ in range(20):
            data=await self.request('GET','/models?pageSize=100'+('&'+str(httpx.QueryParams({'pageToken':page})) if page else ''))
            out.extend(data.get('models',[])); page=data.get('nextPageToken','')
            if not page: break
        return out
    async def choose(self,embedding=False):
        attr='embed_model' if embedding else 'model'
        value=getattr(self,attr)
        if not value:
            action='embedContent' if embedding else 'generateContent'
            names=[m['name'].removeprefix('models/') for m in await self.models() if action in m.get('supportedGenerationMethods',[]) and m.get('name')]
            if embedding: candidates=[n for n in names if 'embedding' in n and 'experimental' not in n]
            else: candidates=[n for n in names if n.startswith('gemini-') and 'flash' in n and not any(x in n for x in ('image','audio','tts','live','preview','exp','robot','thinking'))]
            if not candidates: raise GeminiError('사용 가능한 모델을 자동 선택하지 못했습니다. .env에 모델을 지정하세요.')
            def score(n):
                m=re.search(r'(\d+)(?:\.(\d+))?',n); return (int(m[1]),int(m[2] or 0),'lite' not in n) if m else (0,0,False)
            value=max(candidates,key=score); setattr(self,attr,value)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',value): raise GeminiError('모델 이름 형식 오류')
        return value
    async def generate(self,prompt,system,structured=False,contents=None,tools=None):
        model=await self.choose(); body={'systemInstruction':{'parts':[{'text':system}]},'contents':contents or [{'role':'user','parts':[{'text':prompt}]}]}
        if structured: body['generationConfig']={'responseMimeType':'application/json'}
        if tools: body['tools']=[{'functionDeclarations':tools}]
        d=await self.request('POST',f'/models/{model}:generateContent',body)
        u=d.get('usageMetadata',{}); self.usage.append({'model':model,'input_tokens':u.get('promptTokenCount',0),'output_tokens':u.get('candidatesTokenCount',0),'thinking_tokens':u.get('thoughtsTokenCount',0),'total_tokens':u.get('totalTokenCount',0)})
        candidates=d.get('candidates',[])
        if not candidates: raise GeminiError('생성 결과 없음: 차단 또는 빈 응답')
        cand=candidates[0]; content=cand.get('content',{}); parts=content.get('parts',[])
        text=''.join(p.get('text','') for p in parts if not p.get('thought'))
        if not text and not any('functionCall' in p for p in parts): raise GeminiError('생성 결과 없음 또는 차단')
        return text,content
    async def embed(self,text):
        model=await self.choose(True)
        d=await self.request('POST',f'/models/{model}:embedContent',{'model':f'models/{model}','content':{'parts':[{'text':text}]}})
        v=d.get('embedding',{}).get('values',[])
        if not v: raise GeminiError('임베딩 응답 없음')
        return model,v
