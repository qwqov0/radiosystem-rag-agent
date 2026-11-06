from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'runtime/packages'))
import uvicorn
if __name__=='__main__':uvicorn.run('battle_api:app',host='127.0.0.1',port=18083,workers=1)
