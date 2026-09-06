"""Locally reconstructed MiniRedis-like target, not the course implementation.
Semantics for unspecified details are documented in LOCAL_EVALUATION.md.
No eval/exec, network or subprocesses. Input is command data only.
"""
import re
import shlex

MUTANTS = (
    'delete_retains_schema', 'mset_partial_commit', 'setv_partial_commit',
    'lrem_negative_forward', 'lrev_noop', 'lset_noop',
    'getrange_exclusive', 'lpush_preserve_order', 'calc_no_store',
    'define_erases_value', 'range_upper_exclusive', 'expr_eager_if',
)

class CommandError(Exception):
    pass

class Store:
    def __init__(self, mutant=None):
        if mutant is not None and mutant not in MUTANTS:
            raise ValueError('unknown mutant')
        self.mutant = mutant
        self.data = {}
        self.schemas = {}
        self.events = set()

    def check(self, key, value, schema=None):
        schema = self.schemas.get(key) if schema is None else schema
        if schema is None:
            return
        kind, params = schema
        if kind == 'integer':
            try:
                value = int(value)
            except ValueError:
                raise CommandError('value is not an integer')
            lo, hi = params
            if value < lo:
                raise CommandError(f'value out of range (min: {lo})')
            if value > hi or (self.mutant == 'range_upper_exclusive' and value == hi):
                raise CommandError(f'value out of range (max: {hi})')
        elif kind == 'string':
            if not re.fullmatch(params, value):
                raise CommandError('value does not match pattern')
        elif value not in params:
            raise CommandError('value not in allowed values: [' + ', '.join(params) + ']')

    def schema(self, args):
        if len(args) < 3 or args[0] != 'TYPE':
            raise CommandError('invalid schema')
        kind = args[1]
        if kind == 'integer' and len(args) == 5 and args[2] == 'RANGE':
            lo, hi = int(args[3]), int(args[4])
            if lo > hi:
                raise CommandError('invalid range')
            return kind, (lo, hi)
        if kind == 'string' and len(args) == 4 and args[2] == 'PATTERN':
            re.compile(args[3])
            return kind, args[3]
        if kind == 'enum' and len(args) == 4 and args[2] == 'VALUES':
            return kind, args[3].split(',')
        raise CommandError('invalid schema')

    def string(self, key, default=''):
        value = self.data.get(key, default)
        if isinstance(value, list):
            raise CommandError('wrong type')
        return value

    def listing(self, key):
        value = self.data.get(key, [])
        if not isinstance(value, list):
            raise CommandError('wrong type')
        return value

    @staticmethod
    def interval(value, start, stop, exclusive=False):
        n = len(value)
        start = start + n if start < 0 else start
        stop = stop + n if stop < 0 else stop
        return value[max(0, start):max(0, min(n, stop + (0 if exclusive else 1)))]

    def expression(self, text):
        tokens = re.findall(r'\(|\)|[^\s()]+', text)
        pos = 0
        def parse(depth=0):
            nonlocal pos
            if depth > 100:
                raise CommandError('expression too deeply nested')
            if pos >= len(tokens):
                raise CommandError('syntax error: invalid expression')
            token = tokens[pos]; pos += 1
            if token == '(':
                if pos >= len(tokens):
                    raise CommandError('syntax error: invalid expression')
                op = tokens[pos]; pos += 1
                children = []
                while pos < len(tokens) and tokens[pos] != ')':
                    children.append(parse(depth + 1))
                if pos >= len(tokens):
                    raise CommandError('syntax error: invalid expression')
                pos += 1
                return (op, children)
            if token == ')':
                raise CommandError('syntax error: invalid expression')
            return token
        tree = parse()
        if pos != len(tokens):
            raise CommandError('syntax error: invalid expression')
        def calc(node):
            if isinstance(node, str):
                if node.startswith('$'):
                    key = node[1:]
                    if key not in self.data:
                        raise CommandError('undefined variable: ' + key)
                    try:
                        return int(self.string(key))
                    except ValueError:
                        raise CommandError('variable is not an integer: ' + key)
                try:
                    return int(node)
                except ValueError:
                    raise CommandError('syntax error: invalid expression')
            op, children = node
            count = 3 if op == 'if' else 1 if op == 'not' else 2
            if len(children) != count:
                raise CommandError("wrong number of arguments for '" + op + "'")
            if op == 'if' and self.mutant != 'expr_eager_if':
                return calc(children[1] if calc(children[0]) else children[2])
            v = [calc(c) for c in children]
            if op == 'if': return v[1] if v[0] else v[2]
            if op == 'not': return int(not v[0])
            a, b = v
            if op == '+': return a + b
            if op == '-': return a - b
            if op == '*': return a * b
            if op in ['/', '%']:
                if b == 0: raise CommandError('division by zero')
                q = (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1)
                return q if op == '/' else a - q * b
            if op == '<': return int(a < b)
            if op == '>': return int(a > b)
            if op == '<=': return int(a <= b)
            if op == '>=': return int(a >= b)
            if op == '==': return int(a == b)
            if op == '!=': return int(a != b)
            if op == 'and': return int(bool(a) and bool(b))
            if op == 'or': return int(bool(a) or bool(b))
            raise CommandError('unknown operator')
        return str(calc(tree))

    def command(self, command):
        try:
            if not isinstance(command, str) or len(command) > 10000:
                raise CommandError('invalid command')
            parts = shlex.split(command)
            if not parts: raise CommandError('empty command')
            op, args = parts[0], parts[1:]
            self.events.add(op)
            if op == 'EVAL': return self.expression(command.split(None, 1)[1])
            if op == 'CALC':
                if len(args) < 2: raise CommandError('wrong number of arguments')
                key = args[0]; value = self.expression(command.split(None, 2)[2]); self.check(key, value)
                if self.mutant != 'calc_no_store': self.data[key] = value
                return value
            exact = {'SET':2,'GET':1,'INCR':1,'DECR':1,'INCRBY':2,'DECRBY':2,'APPEND':2,'STRLEN':1,'GETRANGE':3,'LPOP':1,'RPOP':1,'LLEN':1,'LRANGE':3,'LINDEX':2,'LSET':3,'LREM':3,'LREV':1,'VALIDATE':1}
            if op in exact and len(args) != exact[op]: raise CommandError('wrong number of arguments')
            if not args: raise CommandError('wrong number of arguments')
            key = args[0]
            if op == 'SET': self.check(key,args[1]);self.data[key]=args[1];return 'OK'
            if op == 'GET': return self.string(key,'(nil)')
            if op == 'DEL':
                count = 0
                for k in args:
                    count += int(k in self.data);self.data.pop(k,None)
                    if self.mutant != 'delete_retains_schema':self.schemas.pop(k,None)
                return str(count)
            if op == 'EXISTS': return str(sum(k in self.data for k in args))
            if op in ['INCR','DECR','INCRBY','DECRBY']:
                try: value = int(self.string(key,'0'))
                except ValueError: raise CommandError('value is not an integer')
                delta = int(args[1]) if op.endswith('BY') else 1
                value += -delta if op.startswith('DECR') else delta
                self.check(key,str(value));self.data[key]=str(value);return str(value)
            if op == 'APPEND':
                value=self.string(key)+args[1];self.check(key,value);self.data[key]=value;return str(len(value))
            if op == 'STRLEN': return str(len(self.string(key)))
            if op == 'GETRANGE': return self.interval(self.string(key),int(args[1]),int(args[2]),self.mutant=='getrange_exclusive')
            if op == 'MSET':
                if len(args)%2: raise CommandError('wrong number of arguments')
                pairs=list(zip(args[::2],args[1::2]))
                if self.mutant == 'mset_partial_commit':
                    for k,v in pairs:self.check(k,v);self.data[k]=v
                else:
                    for k,v in pairs:self.check(k,v)
                    self.data.update(pairs)
                return 'OK'
            if op == 'MGET': return '\n'.join(self.string(k,'(nil)') for k in args)
            if op in ['LPUSH','RPUSH']:
                if len(args)<2:raise CommandError('wrong number of arguments')
                values=list(self.listing(key))
                if op=='RPUSH':values.extend(args[1:])
                elif self.mutant=='lpush_preserve_order':values=args[1:]+values
                else:values=list(reversed(args[1:]))+values
                self.data[key]=values;return str(len(values))
            if op in ['LPOP','RPOP','LLEN','LRANGE','LINDEX','LSET','LREM','LREV']:
                values=list(self.listing(key))
                if op=='LLEN':return str(len(values))
                if op=='LRANGE':return '\n'.join(self.interval(values,int(args[1]),int(args[2]))) or '(empty list)'
                if op in ['LPOP','RPOP']:
                    if not values:return '(nil)'
                    v=values.pop(0 if op=='LPOP' else -1);self.data[key]=values;return v
                if op in ['LINDEX','LSET']:
                    idx=int(args[1])
                    if idx<0:idx+=len(values)
                    if not 0<=idx<len(values):
                        if op=='LINDEX':return '(nil)'
                        raise CommandError('no such key' if key not in self.data else 'index out of range')
                    if op=='LINDEX':return values[idx]
                    if self.mutant!='lset_noop':values[idx]=args[2]
                    self.data[key]=values;return 'OK'
                if op=='LREV':
                    if key not in self.data:raise CommandError('no such key')
                    if self.mutant!='lrev_noop':values.reverse()
                    self.data[key]=values;return 'OK'
                count=int(args[1]);indices=[i for i,v in enumerate(values) if v==args[2]]
                if count<0 and self.mutant!='lrem_negative_forward':indices.reverse()
                removed=set(indices[:abs(count)] if count else indices)
                if key in self.data:self.data[key]=[v for i,v in enumerate(values) if i not in removed]
                return str(len(removed))
            if op in ['DEFINE','SETV']:
                offset=1 if op=='DEFINE' else 2
                schema=self.schema(args[offset:])
                if op=='SETV':
                    if self.mutant=='setv_partial_commit':self.schemas[key]=schema;self.data[key]=args[1]
                    self.check(key,args[1],schema);self.data[key]=args[1]
                elif self.mutant=='define_erases_value':self.data.pop(key,None)
                self.schemas[key]=schema;return 'OK'
            if op=='VALIDATE':
                if key not in self.data:raise CommandError('no such key')
                self.check(key,self.string(key));return 'OK'
            raise CommandError('unknown command')
        except (CommandError,ValueError,IndexError,re.error) as error:
            self.events.add('error')
            return 'ERR '+str(error)


def run(sequence, mutant=None):
    store=Store(mutant)
    return [store.command(c) for c in sequence]
