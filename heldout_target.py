"""Additional synthetic defects; never imported by generation/feedback code.
Same author/reference as development fixtures: not independent external evidence.
"""
import shlex
from local_target import Store

MUTANTS=('decrby_sign','mget_reorders','lindex_negative_offone','rpop_wrong_end',
         'exists_deduplicates','mset_loses_last','append_returns_old_length','expr_mod_sign')

class HeldoutStore(Store):
    def __init__(self,mutant=None):
        super().__init__()
        if mutant not in MUTANTS:raise ValueError('unknown heldout mutant')
        self.heldout=mutant
    def command(self,command):
        try:p=shlex.split(command)
        except ValueError:return super().command(command)
        m=self.heldout
        if len(p)<2:return super().command(command)
        op,k=p[:2]
        if m=='decrby_sign' and op=='DECRBY':
            return super().command('INCRBY '+shlex.join(p[1:]))
        if m=='mget_reorders' and op=='MGET':
            return super().command(shlex.join([op]+sorted(p[1:])))
        if m=='lindex_negative_offone' and op=='LINDEX' and len(p)==3:
            try:
                if int(p[2])<0 and isinstance(self.data.get(k),list):
                    idx=len(self.data[k])+int(p[2])+1
                    return self.data[k][idx] if 0<=idx<len(self.data[k]) else '(nil)'
            except ValueError:pass
        if m=='rpop_wrong_end' and op=='RPOP':return super().command(shlex.join(['LPOP']+p[1:]))
        if m=='exists_deduplicates' and op=='EXISTS':return str(sum(k in self.data for k in set(p[1:])))
        if m=='mset_loses_last' and op=='MSET' and len(p)>=5 and len(p)%2==1:
            previous=self.data.copy();result=super().command(command)
            if result=='OK':
                if p[-2] in previous:self.data[p[-2]]=previous[p[-2]]
                else:self.data.pop(p[-2],None)
            return result
        if m=='append_returns_old_length' and op=='APPEND':
            old=self.data.get(k,'');result=super().command(command)
            if not result.startswith('ERR') and isinstance(old,str):return str(len(old))
            return result
        result=super().command(command)
        if m=='expr_mod_sign' and op=='EVAL' and '(%' in command and not result.startswith('ERR'):
            return str(abs(int(result)))
        return result

def run(sequence,mutant):
    s=HeldoutStore(mutant)
    return [s.command(c) for c in sequence]
