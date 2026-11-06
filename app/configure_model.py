from pathlib import Path
import argparse,json,secrets
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:18082/v1/chat/completions');p.add_argument('--model',default='qwen2.5-7b-instruct-q4_k_m');a=p.parse_args()
r=Path(__file__).parent/'runtime';r.mkdir(exist_ok=True)
(r/'backend.json').write_text(json.dumps(dict(url=a.url,model=a.model,device='local')),encoding='utf8')
key=r/'local_api_key.txt'
if not key.exists():key.write_text(secrets.token_hex(32),encoding='utf8')
print('Local configuration saved. Pass runtime/local_api_key.txt via llama-server --api-key-file.')
