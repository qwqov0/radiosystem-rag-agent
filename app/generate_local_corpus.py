"""Build a local RAG corpus from this checkout; no historical course data is included."""
from pathlib import Path
import json,hashlib,argparse
ROOT=Path(__file__).resolve().parent
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT.parent/'engine/src');p.add_argument('--output',type=Path,default=ROOT/'corpus');a=p.parse_args()
 rows=[];manifest=[]
 for f in sorted(a.source.rglob('*')):
  if not f.is_file() or f.suffix.lower() not in ('.h','.hpp','.cpp','.py','.md','.txt'):continue
  lines=f.read_text(encoding='utf-8-sig').splitlines();name=f.relative_to(a.source).as_posix();start=0
  manifest.append(dict(source=name,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
  while start<len(lines):
   end=start;length=0
   while end<len(lines) and (length<1100 or end==start):length+=len(lines[end])+1;end+=1
   rows.append(dict(id=f'{name}:L{start+1}-{end}',source=name,status='source_snapshot_not_runtime_proof',text='\n'.join(f'{i+1}: {lines[i]}' for i in range(start,end)),start_line=start+1,end_line=end))
   if end==len(lines):break
   start=max(start+1,end-5)
 if not rows:raise SystemExit('No supported source files found.')
 a.output.mkdir(parents=True,exist_ok=True)
 (a.output/'chunks.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n',encoding='utf8')
 (a.output/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
 print(f'Generated {len(rows)} local chunks from {len(manifest)} source files.')
if __name__=='__main__':main()
