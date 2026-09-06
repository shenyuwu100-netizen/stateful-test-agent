"""Data-only, budgeted generation and developer-fixture feedback. No holdout import."""
import json,re,shlex,hashlib,urllib.request,urllib.error,time
from pathlib import Path
from local_target import Store,run,MUTANTS
import os
from urllib.parse import urlparse

COMMANDS=set('SET GET DEL EXISTS INCR DECR INCRBY DECRBY APPEND STRLEN GETRANGE MSET MGET LPUSH RPUSH LPOP RPOP LLEN LRANGE LINDEX LSET LREM LREV EVAL CALC DEFINE SETV VALIDATE'.split())
SPEC='''Generate stateful tests for a LOCAL MiniRedis-like string/list store. Return JSON only, no code: {"sequences":[["SET a 1","GET a"]],"relations":[{"a":["SET a 1","GET a"],"b":["INCR a","GET a"],"relation":"EQ"}]}. Each sequence and each relation side starts with a fresh store. Sequences compare ALL outputs with a reference. Relations compare ONLY the final outputs of a and b (EQ equal or NE different). BUDGET is an upper bound on the TOTAL number of commands including BOTH relation sides. At most 16 commands per sequence. Keys/values simple ASCII words or signed integers. Empty strings can be quoted.
Commands: SET key value overwrites string, OK. GET returns string or (nil). DEL keys deletes values AND schema, returns deletion count. EXISTS keys returns existing count (duplicates counted). Missing numeric key starts 0. INCR/DECR/INCRBY/DECRBY return new integer, numeric type errors preserve state. APPEND appends and returns new length; STRLEN length or 0. GETRANGE inclusive end, negative indices supported. MSET key value pairs is atomic including validation, returns OK; MGET keys returns values in request order joined by newline. LPUSH pushes args one at a time at head, RPUSH pushes at tail; both return length. LPOP/RPOP remove respective end or return (nil). LLEN length. LRANGE inclusive and negative indices, newline-separated or (empty list). LINDEX supports negative indices, out of range (nil). LSET changes index, OK. LREM key count value removes first count occurrences if positive, last abs(count) if negative, all if zero, returns count. LREV reverses, OK; missing key error. Empty lists retain key.
EVAL S-expressions with binary +,-,*,/,%,<,>,<=,>=,==,!=,and,or; unary not; ternary if (lazy selected branch). Variables $key, integers, nesting. Division truncates toward zero, remainder a-trunc(a/b)*b. CALC key expr evaluates, stores string and returns value. DEFINE key TYPE integer RANGE lo hi, TYPE enum VALUES a,b,c, or TYPE string PATTERN "^[a-z]+@[a-z]+$" installs schema without changing value. SETV key value TYPE ... atomically sets schema+value or changes nothing on error. VALIDATE key returns OK or ERR. Range endpoints inclusive. Numeric writes, APPEND and CALC also validate. Failed writes preserve state. Error messages need not be hardcoded in tests. This is a reconstruction, not the original course binary. No external access, Python, URLs, arbitrary regex, or code execution.'''

def validate_suite(raw,budget):
    if not isinstance(raw,dict) or set(raw)-{'sequences','relations'}:raise ValueError('invalid envelope')
    seqs=raw.get('sequences',[]);rels=raw.get('relations',[])
    if not isinstance(seqs,list) or not isinstance(rels,list) or len(seqs)+len(rels)>100:raise ValueError('invalid collections')
    count=0
    def sequence(s):
        nonlocal count
        if not isinstance(s,list) or not 1<=len(s)<=16:raise ValueError('sequence length')
        for cmd in s:
            if not isinstance(cmd,str) or not 1<=len(cmd)<=512 or any(c in cmd for c in '\n\r\x00'):raise ValueError('invalid command text')
            p=shlex.split(cmd)
            if not p or p[0] not in COMMANDS:raise ValueError('unsupported command')
            if cmd.count('(')>32:raise ValueError('expression size')
            if any(len(v)>12 for v in re.findall(r'\d+',cmd)):raise ValueError('integer size')
            if 'PATTERN' in p and p[p.index('PATTERN')+1:]!=['^[a-z]+@[a-z]+$']:raise ValueError('unsupported regex')
            count+=1
    for s in seqs:sequence(s)
    for r in rels:
        if not isinstance(r,dict) or set(r)!={'a','b','relation'} or r['relation'] not in ['EQ','NE']:raise ValueError('invalid relation')
        sequence(r['a']);sequence(r['b'])
    if not 1<=count<=budget:raise ValueError('command budget')
    return {'sequences':seqs,'relations':rels,'commands':count}

def merge(a,b):
    return {'sequences':a['sequences']+b['sequences'],'relations':a['relations']+b['relations'],'commands':a['commands']+b['commands']}

def relation_ok(r,runner):
    a,b=runner(r['a'])[-1],runner(r['b'])[-1]
    return (a==b)==(r['relation']=='EQ')

def evaluate(suite,mutants=MUTANTS,runner=run):
    valid=[];invalid=[]
    for i,r in enumerate(suite['relations']):
        if relation_ok(r,run):valid.append((i,r))
        else:invalid.append(i)
    killed={}
    expected=[run(s) for s in suite['sequences']]
    for m in mutants:
        for i,(s,e) in enumerate(zip(suite['sequences'],expected)):
            if runner(s,m)!=e:killed[m]={'kind':'sequence','index':i};break
        if m not in killed:
            for i,r in valid:
                if not relation_ok(r,lambda s:runner(s,m)):killed[m]={'kind':'relation','index':i};break
    return {'killed':killed,'detected':len(killed),'total':len(mutants),'valid_relations':len(valid),'invalid_relation_indices':invalid}

def feedback(suite):
    result=evaluate(suite)
    ops=set();errors=0
    sequences=suite['sequences']+[r[k] for r in suite['relations'] for k in ['a','b']]
    for s in sequences:
        state=Store()
        for c in s:
            ops.add(c.split()[0]);errors+=state.command(c).startswith('ERR')
    return {'detected_development_defects':result['detected'],'total_development_defects':result['total'],'invalid_relation_indices':result['invalid_relation_indices'],'operations_exercised':sorted(ops),'reference_error_outputs':errors,'commands_so_far':suite['commands'],'note':'These are command categories, NOT source coverage. Add distinct state interactions; never see defect names or source. All attempted commands including invalid relations consume the budget.'}

class APIClient:
    def __init__(self,path=None,max_calls=3):
        if path is not None: raise ValueError('Configure credentials with environment variables')
        base=os.environ.get('LLM_BASE_URL','').rstrip('/')
        key=os.environ.get('LLM_API_KEY','')
        parsed=urlparse(base)
        if not key or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('Set LLM_BASE_URL to an HTTPS API base and LLM_API_KEY')
        if not base.endswith('/v1'): base+='/v1'
        self.record={'url':base,'key':key}
        self.model=os.environ.get('LLM_MODEL','gpt-5.6-luna')
        self.max_calls=max_calls;self.attempts=0;self.usage=[]
    def generate(self,budget,prior=None):
        if self.attempts>=self.max_calls:raise RuntimeError('API call cap reached')
        self.attempts+=1
        prompt=SPEC.replace('BUDGET',str(budget))
        messages=[{'role':'system','content':prompt}]
        data={'instruction':'Generate useful sequences and metamorphic relations within the total command budget.'}
        if prior is not None:data.update(previous_suite=prior,feedback=feedback(prior),instruction='Add tests within your remaining allocation. Do not repeat the earlier suite.')
        messages.append({'role':'user','content':json.dumps(data)})
        payload={'model':self.model,'reasoning_effort':'low','max_completion_tokens':3000,'messages':messages}
        req=urllib.request.Request(self.record['url']+'/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+self.record['key'],'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
        started=time.monotonic();entry={'attempt':self.attempts,'max_completion_tokens':3000,'prompt_sha256':hashlib.sha256(json.dumps(messages).encode()).hexdigest()};self.usage.append(entry)
        try:
            with urllib.request.urlopen(req,timeout=90) as response:result=json.load(response)
            entry.update(seconds=round(time.monotonic()-started,2),usage=result.get('usage'),model=result.get('model'))
            choice=result['choices'][0];entry['finish_reason']=choice.get('finish_reason')
            if choice.get('finish_reason')!='stop':raise ValueError('incomplete response')
            text=choice['message'].get('content') or ''
            if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
            suite=validate_suite(json.loads(text),budget);entry['status']='ok';return suite
        except Exception as error:
            entry.update(status='failed',error_type=type(error).__name__)
            if isinstance(error,urllib.error.HTTPError):entry['http_status']=error.code
            # Deliberately exclude raw service body, credentials and exception text.
            raise RuntimeError('API generation failed; see sanitized attempt metadata') from None
