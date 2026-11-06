"""Preregistered paired position/length extension using the paper's original data."""
from pathlib import Path
import json,gzip,random,hashlib,datetime,time,statistics,argparse,re
from model_client import chat,backend
ROOT=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def freeze():
 out=ROOT/'results/paper_gpu';out.mkdir(exist_ok=True);path=out/'protocol.json'
 if path.exists():return json.loads(path.read_text(encoding='utf-8'))
 sources={};indices={}
 for count in [75,140,300]:
  p=ROOT/f'paper/author_code/kv_retrieval_data/kv-retrieval-{count}_keys.jsonl.gz';sources[str(count)]=sha(p)
  with gzip.open(p,'rt',encoding='utf-8') as f:n=sum(1 for _ in f)
  indices[str(count)]=sorted(random.Random(42+count).sample(list(range(3,n)),20))
 protocol=dict(version='gpu_position_length_v1',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),backend=backend(),seed=42,temperature=0,max_output_tokens=192,pair_counts=[75,140,300],relative_positions=[0,.5,1],samples_per_length=20,sample_indices=indices,source_sha256=sources,positions='round((pair_count-1)*relative_position)',ordering='shuffle length/sample blocks and rotate position order by block to reduce cache-order effects',cache_prompt=False,context_shift=False,scope='Task-protocol replication with original author data and prompt, different quantized Qwen model. Not reproduction of original model figure points.',scoring='author case-insensitive gold-value substring; also report strict UUID exact match, finish_reason, latency, and paired bootstrap 95 percent intervals',bootstrap_seed=20261022,bootstrap_repeats=10000,limitations=['20 samples per length, 3 positions, no claim of universal U-shape.','Length datasets contain different sampled base examples; length effects are not a clean paired same-item comparison.','Q4_K_M weights and Q8 KV differ from paper model settings.'])
 path.write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8');print('PAPER PROTOCOL FROZEN',sha(path),flush=True);return protocol
def summarize(out,protocol):
 rows=[json.loads(s) for s in (out/'predictions.jsonl').read_text(encoding='utf-8').splitlines()];rows=list({(x['pairs'],x['sample'],x['position']):x for x in rows}.values());summary=[];paired=[]
 for count in protocol['pair_counts']:
  positions=[0,round((count-1)*.5),count-1]
  for pos in positions:
   a=[x for x in rows if x['pairs']==count and x['position']==pos];valid=[x for x in a if 'error' not in x];values=[int(x.get('correct',False)) for x in a]
   rng=random.Random(protocol['bootstrap_seed']+count+pos);bs=sorted(sum(rng.choice(values) for _ in values)/len(values) for _ in range(10000)) if values else []
   summary.append(dict(pairs=count,position=pos,n=len(a),correct=sum(values),accuracy=sum(values)/len(values) if values else None,ci95=[bs[249],bs[9749]] if bs else None,strict_exact=sum(x.get('strict_exact',False) for x in a),errors=len(a)-len(valid),truncated=sum(x.get('finish_reason')=='length' for x in a),mean_seconds=statistics.mean(x['seconds'] for x in valid) if valid else None))
  by={(x['sample'],x['position']):x for x in rows if x['pairs']==count}
  samples=[s for s in protocol['sample_indices'][str(count)] if all((s,p) in by for p in positions)]
  delta=[(int(by[s,positions[0]].get('correct',False))+int(by[s,positions[2]].get('correct',False)))/2-int(by[s,positions[1]].get('correct',False)) for s in samples]
  rng=random.Random(42+count);bs=sorted(sum(rng.choice(delta) for _ in delta)/len(delta) for _ in range(10000)) if delta else []
  paired.append(dict(pairs=count,n=len(delta),edge_mean_minus_middle=sum(delta)/len(delta) if delta else None,paired_bootstrap_ci95=[bs[249],bs[9749]] if bs else None,interpretation='Positive means edge advantage; zero-inclusive interval is inconclusive. Degenerate all-equal samples yield degenerate bootstrap intervals, not certainty.'))
 (out/'summary.json').write_text(json.dumps(dict(conditions=summary,paired=paired,expected_calls=180,completed_calls=len(rows)),indent=2),encoding='utf-8');return len(rows)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--freeze-only',action='store_true');args=ap.parse_args();protocol=freeze()
 if args.freeze_only:return
 assert backend()['model']==protocol['backend']['model'];out=ROOT/'results/paper_gpu';path=out/'predictions.jsonl'
 done={(x['pairs'],x['sample'],x['position']) for s in path.read_text(encoding='utf-8').splitlines() if (x:=json.loads(s)) and 'error' not in x} if path.exists() else set()
 template=(ROOT/'paper/author_code/src/lost_in_the_middle/prompts/kv_retrieval.prompt').read_text(encoding='utf-8');tasks=[]
 for count in protocol['pair_counts']:
  source=ROOT/f'paper/author_code/kv_retrieval_data/kv-retrieval-{count}_keys.jsonl.gz';assert sha(source)==protocol['source_sha256'][str(count)]
  with gzip.open(source,'rt',encoding='utf-8') as f:allrows=[json.loads(s) for s in f]
  for i in protocol['sample_indices'][str(count)]:tasks.append((count,i,allrows[i]))
 random.Random(42).shuffle(tasks)
 for block,(count,i,row) in enumerate(tasks):
  gold=[x for x in row['ordered_kv_records'] if x[0]==row['key']];assert len(gold)==1 and gold[0][1]==row['value'];others=[x for x in row['ordered_kv_records'] if x[0]!=row['key']]
  positions=[0,round((count-1)*.5),count-1];offset=block%3;positions=positions[offset:]+positions[:offset]
  for pos in positions:
   if (count,i,pos) in done:continue
   records=list(others);records.insert(pos,gold[0]);assert len(records)==count
   prompt=template.format(formatted_kv_records=json.dumps(dict(records)),key=row['key']);rec=dict(pairs=count,sample=i,position=pos,key=row['key'],gold=row['value'],prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
   try:
    response=chat([dict(role='user',content=prompt)],max_tokens=192,config=protocol['backend'],cache_prompt=False);rec.update(response);rec['correct']=row['value'].lower() in rec['text'].lower();rec['strict_exact']=rec['text'].strip().strip('`\" \n').lower()==row['value'].lower()
   except Exception as e:rec['error']=repr(e)
   with path.open('a',encoding='utf-8') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
   print('PAPER',count,i,pos,rec.get('correct'),rec.get('finish_reason'),round(rec.get('seconds',0),2),flush=True)
  summarize(out,protocol)
 print('PAPER GPU COMPLETE',summarize(out,protocol),flush=True)
if __name__=='__main__':main()
