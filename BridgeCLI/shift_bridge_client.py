"""Copy into SHIFT BRIDGE Python backend or adapt to its language.
Never return the local auth token to a browser. Server must run on same host.
"""
import os,httpx
class BridgeClient:
    def __init__(self,base_url=None,token=None):
        self.base=(base_url or os.getenv('BRIDGE_BASE_URL','http://127.0.0.1:8011')).rstrip('/')
        self.token=token or os.getenv('HYBRID_API_AUTH_TOKEN','')
        if not self.token: raise ValueError('BRIDGE 인증 토큰을 백엔드 환경변수에서 설정하세요.')
    async def call(self,task,prompt='',mode='auto',metadata=None):
        async with httpx.AsyncClient(timeout=480) as c:
            r=await c.post(self.base+'/v1/bridge',headers={'Authorization':'Bearer '+self.token},json={'task':task,'prompt':prompt,'mode':mode,'metadata':metadata or {}})
            r.raise_for_status(); return r.json()['result']
