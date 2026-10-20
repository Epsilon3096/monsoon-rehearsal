import hashlib,json,shutil,sys
from pathlib import Path
root=Path.cwd()
sys.path.insert(0,str(root/'outputs/monsoon-rehearsal'))
from monsoon.bench_conservative import verify_conservative_result,conservative_identity
folder=root/'work/v07-browser-attempts/ae817-dry-workflow'
result=json.loads((folder/'extracted/result.json').read_bytes())
result['artifact_directory']=str(folder/'extracted')
first=verify_conservative_result(result)
relocated=folder/'relocated evidence'
shutil.copytree(folder/'extracted',relocated)
result['artifact_directory']=str(relocated)
second=verify_conservative_result(result)
record={'download_sha256':hashlib.sha256((folder/'download.zip').read_bytes()).hexdigest(),'download_files':len(list((folder/'extracted').rglob('*'))),'original_extraction':first,'relocated_without_rewriting_evidence':second,'current_identity':conservative_identity(),'passed':first['valid'] and second['valid'] and result['valid']}
(folder/'download-verification.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps({'passed':record['passed'],'download_files':record['download_files']}))
assert record['passed']
