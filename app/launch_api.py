from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'runtime/packages'))
import uvicorn
uvicorn.run('api:app',host='127.0.0.1',port=18081,workers=1)
