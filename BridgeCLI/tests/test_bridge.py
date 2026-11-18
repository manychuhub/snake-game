import os,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import api_server as server
from memory import Memory
from gemini_api import Gemini
class FakeGemini:
    def __init__(self): self.usage=[]; self.calls=0
    async def generate(self,prompt,system,structured=False,contents=None,tools=None):
        self.calls+=1; self.usage.append(dict(model='test-only',input_tokens=10,output_tokens=5,thinking_tokens=0,total_tokens=15))
        if tools and self.calls==1: return '',{'role':'model','parts':[{'functionCall':{'name':'search_records','args':{'query':'SERVER-32'}}}]}
        if structured: return json.dumps({'equipment':'SERVER-32','ticket':'T-32','status':'완료','action':'RAM 교체','result':'정상'}),{}
        return '테스트 결과 [R1]',{'role':'model','parts':[{'text':'테스트 결과 [R1]'}]}
    async def embed(self,text): return 'fake-embedding',[1,0]
class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Memory(Path(self.tmp.name)/'test.db'); self.patches=[patch.object(server,'mem',self.store),patch.object(server,'TOKEN','test-secret'),patch.object(server,'Gemini',FakeGemini)]
        for p in self.patches:p.start()
        self.client=TestClient(server.app); self.h={'Authorization':'Bearer test-secret'}
    def tearDown(self):
        self.client.close()
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def post(self,task,prompt='',**kwargs): return self.client.post('/v1/bridge',headers=self.h,json={'task':task,'prompt':prompt,**kwargs})
    def add(self):
        r=self.post('analyze','SERVER-32 RAM 교체 정상').json()['result']; self.assertEqual(r['fields']['cause'],'미확인'); self.assertFalse(r['approved']); return r['record_id']
    def approve(self,i): self.assertEqual(self.client.put('/v1/records/'+str(i),headers=self.h,json={'approved':True}).status_code,200)
    def test_auth(self): self.assertEqual(self.client.get('/v1/records').status_code,401); self.assertEqual(self.client.get('/health').status_code,200)
    def test_analysis_approval_persistence(self):
        i=self.add(); self.assertEqual(self.store.search('SERVER-32'),[]); self.approve(i); self.assertEqual(Memory(self.store.path).search('SERVER-32')[0]['id'],i)
    def test_handover(self):
        self.approve(self.add()); x=self.post('handover').json()['result']; self.assertFalse(x['approved']); self.assertEqual(len(x['sources']),1); self.assertEqual(self.client.put('/v1/reports/'+str(x['report_id']),headers=self.h,json={'approved':True,'content':'수정된 내용'}).status_code,200); self.assertEqual(self.store.reports()[0]['content'],'수정된 내용')
    def test_agent(self):
        self.approve(self.add()); x=self.post('assistant','SERVER-32 이전 기록?',mode='agent'); self.assertEqual(x.status_code,200,x.text); self.assertEqual(x.json()['result']['tool_trace'][0]['tool'],'search_records'); self.assertEqual(x.json()['result']['sources'][0]['source'],'R1')
    def test_index(self):
        self.approve(self.add()); self.assertEqual(self.client.post('/v1/index',headers=self.h).json()['indexed'],1); x=self.post('search','검색',metadata={'semantic':True}).json(); self.assertEqual(x['result']['sources'][0]['source'],'R1')
    def test_document(self):
        self.client.post('/v1/documents',headers=self.h,json={'name':'manual','page':3,'text':'RAM 점검 절차'}); r=self.post('document','RAM 점검'); self.assertEqual(r.json()['result']['sources'][0]['page'],3)
    def test_invalid_attachment(self): self.assertEqual(self.post('voice','',attachment_b64='invalid',mime_type='audio/wav').status_code,422)
    def test_usage(self): self.add(); self.assertEqual(self.client.get('/v1/usage',headers=self.h).json()['generation'][0]['total_tokens'],15)
    def test_other_tasks(self):
        for t in ['chat','audit','repeat','priority','translate','improve']:
            self.assertEqual(self.post(t,'sample').status_code,200,t)
    def test_stats(self):
        self.approve(self.add()); self.approve(self.add()); self.assertEqual(server.stats(self.store.rows())['equipment']['SERVER-32'],2)
class RestContract(unittest.IsolatedAsyncioTestCase):
    async def test_request_format(self):
        g=Gemini(key='dummy',model='gemini-test'); captured={}
        async def request(method,path,body=None):
            captured.update(method=method,path=path,body=body); return {'candidates':[{'content':{'role':'model','parts':[{'text':'hello'}]}}],'usageMetadata':{'promptTokenCount':4,'candidatesTokenCount':3,'totalTokenCount':7}}
        g.request=request
        text,_=await g.generate('test','system',True); self.assertEqual(text,'hello'); self.assertEqual(captured['path'],'/models/gemini-test:generateContent'); self.assertEqual(captured['body']['generationConfig']['responseMimeType'],'application/json'); self.assertEqual(g.usage[0]['total_tokens'],7)
if __name__=='__main__': unittest.main()
