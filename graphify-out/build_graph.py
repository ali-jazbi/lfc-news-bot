from pathlib import Path
import json
from graphify.detect import detect, save_manifest
from graphify.extract import extract
from graphify.build import build_from_json
from graphify.cluster import cluster,score_all
from graphify.analyze import god_nodes,surprising_connections,suggest_questions
from graphify.report import generate
from graphify.export import to_json,to_html
from graphify.diagnostics import diagnose_extraction,format_diagnostic_report
root=Path.cwd(); out=root/'graphify-out'; detection=detect(root)
tokens={'input_tokens':0,'output_tokens':0}
r=extract([Path(p) for p in detection['files']['code']], cache_root=root, root=root, parallel=False)
for p in sorted(out.glob('.graphify_semantic_[1234].json')):
    s=json.loads(p.read_text(encoding='utf-8'))
    for key in tokens: tokens[key] += int(s.get(key,0))
    for key in ('nodes','edges','hyperedges'): r.setdefault(key,[]).extend(s.get(key,[]))
G=build_from_json(r,root=str(root),directed=True)
communities=cluster(G); scores=score_all(G,communities)
from collections import Counter
labels={k:', '.join(n for n,_ in Counter(Path(str(G.nodes[n].get('source_file','unknown'))).stem for n in v).most_common(2)) for k,v in communities.items()}
gods=god_nodes(G); surprises=surprising_connections(G,communities); questions=suggest_questions(G,communities,labels)
to_json(G,communities,out/'graph.json',force=True,community_labels=labels)
to_html(G,communities,out/'graph.html',community_labels=labels)
report=generate(G,communities,scores,labels,gods,surprises,detection,tokens,str(root),suggested_questions=questions)
(out/'GRAPH_REPORT.md').write_text(report,encoding='utf-8')
(out/'diagnostics.json').write_text(json.dumps(diagnose_extraction(r,directed=True,root=str(root)),ensure_ascii=False,indent=2,default=str),encoding='utf-8')
(out/'analysis-summary.json').write_text(json.dumps({'nodes':len(G),'edges':G.number_of_edges(),'communities':len(communities),'god_nodes':gods,'surprising_connections':surprises,'questions':questions},ensure_ascii=False,indent=2),encoding='utf-8')
save_manifest(detection['files'],root=str(root))
print('graph',len(G),G.number_of_edges(),len(communities))

(out/'cost.json').write_text(json.dumps({'runs':[dict(tokens,files=detection['total_files'],note='Semantic-agent token estimates; AST extraction uses no LLM')], 'total_input_tokens':tokens['input_tokens'],'total_output_tokens':tokens['output_tokens']},indent=2),encoding='utf-8')
