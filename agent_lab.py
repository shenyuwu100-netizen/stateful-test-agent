"""Reproducible local lab CLI. Offline by default; live uses environment credentials."""
import argparse,json,random,hashlib,datetime,html,statistics
from pathlib import Path
from agent_engine import APIClient,evaluate,merge,run,relation_ok

ROOT=Path(__file__).resolve().parent


def shrink_sequence(seq,mutant,runner,max_checks=1000):
    checks=0;seq=list(seq)
    while checks<max_checks:
        for i in range(len(seq)):
            c=seq[:i]+seq[i+1:];checks+=1
            if c and run(c)!=runner(c,mutant):seq=c;break
            if checks>=max_checks:return seq,checks,False
        else:return seq,checks,True
    return seq,checks,False

def shrink_relation(relation,mutant,runner,max_checks=1000):
    r={**relation,'a':list(relation['a']),'b':list(relation['b'])};checks=0
    while checks<max_checks:
        changed=False
        for side in ['a','b']:
            for i in range(len(r[side])):
                if len(r[side])==1:continue
                c={**r,side:r[side][:i]+r[side][i+1:]};checks+=1
                if relation_ok(c,run) and not relation_ok(c,lambda s:runner(s,mutant)):
                    r=c;changed=True;break
                if checks>=max_checks:return r,checks,False
            if changed:break
        if not changed:return r,checks,True
    return r,checks,False

def freeze():
    files=['heldout_target.py','local_target.py','agent_engine.py','agent_lab.py']
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}

def summarize_suite(suite):
    # Holdout imported only at evaluation, after generation was finished or stopped.
    from heldout_target import MUTANTS,run as heldout_run
    return {'commands':suite['commands'],'development':evaluate(suite),'heldout':evaluate(suite,MUTANTS,heldout_run)}

def render(report,path):
    rows=[]
    for name,value in report.get('evaluation',{}).items():
        rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [name,value['commands'],str(value['development']['detected'])+'/12',str(value['heldout']['detected'])+'/8',value['development']['invalid_relation_indices']])+'</tr>')
    baselines=''
    for name,values in report.get('baseline_summary',{}).items():
        baselines+='<p>'+html.escape(name+': '+json.dumps(values,ensure_ascii=False))+'</p>'
    data=html.escape(json.dumps(report,ensure_ascii=False,indent=2))
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>测试 Agent 实验报告</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px;color:#19283c;background:#f5f7fb}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;border:1px solid #dce2eb;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin-top:20px}h1{font-size:28px}</style><h1>测试 Agent 本地实验</h1><p>自建目标与人工缺陷，不是课程成绩。新增缺陷集不进入模型反馈；同一作者编写，不能视为外部独立验证。命令数是预算上限，实际使用量分别列出。</p><table><tr><th>方法</th><th>命令数</th><th>开发集</th><th>新增缺陷集</th><th>无效关系索引</th></tr>'''+''.join(rows)+'</table><h2>基线说明</h2>'+baselines+'<details><summary>展开完整结果、用量和复现用例</summary><pre>'+data+'</pre></details></html>'
    path.write_text(page,encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--budget',type=int,default=120);p.add_argument('--out',default=None);a=p.parse_args()
    if a.budget<20 or a.budget>120:p.error('budget must be 20..120')
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S');out=Path(a.out) if a.out else ROOT/'results'/('lab-'+stamp)
    out.mkdir(parents=True,exist_ok=False)
    report={'started':stamp,'command_budget':a.budget,'fixture_hashes_before_generation':freeze(),'api_attempts':[],'suites':{},'evaluation':{}}
    def save():
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');render(report,out/'report.html')
    save()
    if a.live:
        client=APIClient(max_calls=3)
        try:
            report['suites']['single']=client.generate(a.budget);report['api_attempts']=client.usage;save();print('single generated',flush=True)
            first=client.generate(a.budget//2);report['suites']['agent_round1']=first;report['api_attempts']=client.usage;save();print('agent round 1 generated',flush=True)
            # Unused first-round budget carries forward, while the global cap stays fixed.
            second=client.generate(a.budget-first['commands'],prior=first);report['suites']['agent']=merge(first,second);report['api_attempts']=client.usage;save();print('agent feedback round generated',flush=True)
        except RuntimeError:
            report['generation_error']='Stopped without retry or account/model switch';report['api_attempts']=client.usage;save()
    if not a.live:
        example=json.loads((ROOT/'examples/recorded-run.json').read_text())
        report['suites']=example['suites']
        report['offline_replay_of_recorded_suites']=True
    from heldout_target import MUTANTS,run as heldout_run
    assert report['fixture_hashes_before_generation']==freeze(),'fixtures changed during run'
    report['baseline_summary']={};report['baseline_trials']={}
    report['reproducers']={}
    for name,suite in report['suites'].items():
        result=summarize_suite(suite);report['evaluation'][name]=result
        reproductions={}
        for mutant,w in result['heldout']['killed'].items():
            if w['kind']=='sequence':
                small,checks,minimal=shrink_sequence(suite['sequences'][w['index']],mutant,heldout_run)
                reproductions[mutant]={'kind':'sequence','commands':small,'expected':run(small),'actual':heldout_run(small,mutant),'checks':checks,'one_minimal':minimal}
            else:
                small,checks,minimal=shrink_relation(suite['relations'][w['index']],mutant,heldout_run)
                reproductions[mutant]={'kind':'relation','relation':small,'reference_valid':relation_ok(small,run),'mutant_valid':relation_ok(small,lambda s:heldout_run(s,mutant)),'checks':checks,'one_minimal':minimal}
        report['reproducers'][name]=reproductions
    report['known_total_tokens']=sum((v.get('usage') or {}).get('total_tokens',0) for v in report['api_attempts'])
    report['unknown_usage_attempts']=sum(v.get('usage') is None for v in report['api_attempts'])
    save();print(json.dumps({'output':str(out),'evaluation':{n:{k:v for k,v in r.items() if k=='commands' or k in ['development','heldout']} for n,r in report['evaluation'].items()},'baseline':report['baseline_summary'],'known_tokens':report['known_total_tokens']},ensure_ascii=False))
if __name__=='__main__':main()
