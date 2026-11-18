import argparse,json,sys,base64,mimetypes
from pathlib import Path
import httpx
from config import BASE_URL,TOKEN,TIMEOUT

def main():
    p=argparse.ArgumentParser(description='BRIDGE CLI — 로컬 AI 엔진'); sub=p.add_subparsers(dest='task',required=True)
    for name in ['chat','analyze','handover','audit','search','repeat','priority','translate','improve','assistant','voice','document','handover-report','doc-analyze']:
        s=sub.add_parser(name); s.add_argument('prompt',nargs='?',default=''); s.add_argument('--shift',default=''); s.add_argument('--mode',choices=['auto','api','agent'],default='auto'); s.add_argument('--file'); s.add_argument('--semantic',action='store_true'); s.add_argument('--target',default='ko'); s.add_argument('--project',default=''); s.add_argument('--json',action='store_true')
    for name in ['status','models','usage','records','reports','index']: sub.add_parser(name)
    for name in ['approve-record','approve-report']:
        s=sub.add_parser(name); s.add_argument('id',type=int)
    a=p.parse_args(); headers={'Authorization':'Bearer '+TOKEN}; task=a.task
    try:
        with httpx.Client(timeout=TIMEOUT*5) as c:
            if task=='status': r=c.get(BASE_URL+'/health')
            elif task in ['models','usage','records','reports']: r=c.get(BASE_URL+'/v1/'+task,headers=headers)
            elif task=='index': r=c.post(BASE_URL+'/v1/index',headers=headers)
            elif task.startswith('approve-'):
                if input(f'{a.id}번 항목을 승인합니까? (yes/no): ').lower()!='yes': return
                r=c.put(BASE_URL+'/v1/'+('records' if task=='approve-record' else 'reports')+'/'+str(a.id),headers=headers,json={'approved':True})
            else:
                prompt=a.prompt or (f'{a.project} 인수인계 보고서' if a.project else '')
                if task=='translate': prompt=f'대상 언어: {a.target}\n원문: {prompt}'
                payload={'task':task,'prompt':prompt,'mode':a.mode,'metadata':{'shift':a.shift,'semantic':a.semantic}}
                if a.file:
                    f=Path(a.file); mime={'.mp3':'audio/mpeg','.m4a':'audio/mp4','.wav':'audio/wav','.webm':'audio/webm','.ogg':'audio/ogg','.flac':'audio/flac','.pdf':'application/pdf','.txt':'text/plain'}.get(f.suffix.lower())
                    if not mime or f.stat().st_size>10_000_000: raise ValueError('지원하지 않는 파일 또는 10MB 초과')
                    payload.update({'attachment_b64':base64.b64encode(f.read_bytes()).decode(),'mime_type':mime})
                r=c.post(BASE_URL+'/v1/bridge',headers=headers,json=payload)
            if r.is_error: print(f'오류 {r.status_code}: {r.text}',file=sys.stderr); return 1
            print(json.dumps(r.json(),ensure_ascii=False,indent=2))
    except (httpx.HTTPError,OSError,ValueError) as e: print('실행 오류: '+str(e),file=sys.stderr); return 1
if __name__=='__main__': sys.exit(main() or 0)
