"""Verify frozen-target outcomes and reproductions, no API/credentials required."""
import argparse,json,hashlib
from pathlib import Path
from agent_lab import summarize_suite,render
from agent_engine import relation_ok
from heldout_target import run as heldout_run
from local_target import run
ROOT=Path(__file__).resolve().parent

def replay(path):
    report=json.loads(Path(path).read_text())
    for filename in ['local_target.py','heldout_target.py']:
        actual=hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()
        if actual!=report['fixture_hashes_before_generation'][filename]:
            raise ValueError('Target changed; use the saved snapshot to reproduce this run')
    checks=0
    for name,suite in report['suites'].items():
        if summarize_suite(suite)!=report['evaluation'][name]:raise AssertionError('evaluation differs: '+name)
        checks+=1
    for name,items in report.get('reproducers',{}).items():
        for mutant,w in items.items():
            if w['kind']=='sequence':
                assert run(w['commands'])==w['expected']
                assert heldout_run(w['commands'],mutant)==w['actual']
                assert w['expected']!=w['actual']
                if w['one_minimal']:
                    s=w['commands']
                    for i in range(len(s)):
                        c=s[:i]+s[i+1:];assert run(c)==heldout_run(c,mutant)
            else:
                r=w['relation'];assert relation_ok(r,run)
                assert not relation_ok(r,lambda s:heldout_run(s,mutant))
            checks+=1
    return {'status':'PASS','verified_checks':checks,'api_calls':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('report',type=Path);a=p.parse_args()
    print(json.dumps(replay(a.report)))
