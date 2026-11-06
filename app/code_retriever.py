"""Code-aware hybrid retrieval; dictionary and priors selected only on dev cases."""
from rag_system import Retriever,tokenize
import re,numpy as np
from langchain_core.runnables import RunnableLambda
class CodeRetriever(Retriever):
 def __init__(self):
  super().__init__();self.chain=RunnableLambda(lambda x:self.retrieve(x['query'],x.get('k',3),x.get('mode','hybrid')))
 def retrieve(self,query,k=3,mode='hybrid'):
  if mode=='dense':return super().retrieve(query,k,'dense')
  translations={'弹药':'ammo','士气':'morale','驻防':'DEFEND STATIONARY','监听':'listen port','地图':'WorldMap','初始化':'initialize constructor','初始':'constructor default','默认':'default','节点':'node','距离':'distance','命令':'command','状态':'state'}
  expansion=' '.join(value for term,value in translations.items() if term in query)
  tokens=tokenize(query+' '+expansion);lexscores=self.bm25.get_scores(tokens);lex=np.argsort(lexscores)[::-1][:24]
  dense=self.db.similarity_search(query,k=min(24,len(self.docs)));scores={}
  for i,d in enumerate(dense):scores[d.metadata['id']]=scores.get(d.metadata['id'],0)+1/(10+i+1)
  for i,j in enumerate(lex):
   key=self.docs[int(j)].metadata['id'];scores[key]=scores.get(key,0)+2/(10+i+1)
  exact=re.findall(r'[A-Za-z_][A-Za-z_0-9]*',query)
  fields=[v for key,v in translations.items() if key in query and key in ['弹药','士气']]
  for row in self.rows:
   text=row['text'];score=scores.get(row['id'],0)
   score+=.09*sum(bool(re.search(r'(?<![A-Za-z_0-9])'+re.escape(t)+r'(?![A-Za-z_0-9])',text,re.I)) for t in exact)
   if fields and any(x in query for x in ['初始','默认','初始化']):
    score+=.11*sum(bool(re.search(re.escape(f)+r'\s*=\s*[0-9]',text)) for f in fields)
   if row['status']=='planning_document_not_implemented_claim' and not any(t in query for t in ['规划','未来','将来']):score*=.5
   scores[row['id']]=score
  keys=sorted(scores,key=lambda key:(-scores[key],key))[:k]
  return [self.byid[key] for key in keys]
