import unittest
from local_target import Store,run,MUTANTS

# Independent explicit expected outputs, rather than only reference/mutant agreement.
CASES={
'delete_retains_schema':(['DEFINE a TYPE integer RANGE 0 2','SET a 1','DEL a','SET a hello','GET a'],['OK','OK','1','OK','hello']),
'mset_partial_commit':(['SET a old','DEFINE b TYPE integer RANGE 0 2','MSET a new b 9','GET a'],['OK','OK','ERR value out of range (max: 2)','old']),
'setv_partial_commit':(['SET a old','SETV a 9 TYPE integer RANGE 0 2','GET a','SET a hello'],['OK','ERR value out of range (max: 2)','old','OK']),
'lrem_negative_forward':(['RPUSH l a b a','LREM l -1 a','LRANGE l 0 -1'],['3','1','a\nb']),
'lrev_noop':(['RPUSH l a b','LREV l','LRANGE l 0 -1'],['2','OK','b\na']),
'lset_noop':(['RPUSH l a b','LSET l 1 z','LINDEX l 1'],['2','OK','z']),
'getrange_exclusive':(['SET a abc','GETRANGE a 0 -1'],['OK','abc']),
'lpush_preserve_order':(['LPUSH l a b c','LRANGE l 0 -1'],['3','c\nb\na']),
'calc_no_store':(['SET a 3','CALC b (+ $a 2)','GET b'],['OK','5','5']),
'define_erases_value':(['SET a 9','DEFINE a TYPE integer RANGE 0 2','GET a'],['OK','OK','9']),
'range_upper_exclusive':(['SETV a 2 TYPE integer RANGE 0 2','GET a'],['OK','2']),
'expr_eager_if':(['EVAL (if 1 7 (/ 1 0))'],['7']),
}
class LocalTargetTests(unittest.TestCase):
 def test_explicit_stateful_cases(self):
  self.assertEqual(set(CASES),set(MUTANTS))
  for mutant,(commands,expected) in CASES.items():
   with self.subTest(mutant=mutant):
    self.assertEqual(run(commands),expected)
    self.assertNotEqual(run(commands,mutant),expected)
 def test_negative_division_java_semantics(self):
  self.assertEqual(run(['EVAL (/ -7 3)','EVAL (% -7 3)']),['-2','-1'])
 def test_errors_and_depth(self):
  for cmd in ['EVAL (+ 1)','EVAL (+ 1 2','EVAL '+ '(+ 1 '*102+'1'+')'*102,'SET a','UNKNOWN a']:
   self.assertTrue(run([cmd])[0].startswith('ERR'),cmd)
 def test_schema_forms(self):
  self.assertEqual(run(['DEFINE e TYPE enum VALUES a,b','SET e a','SET e c','GET e']),['OK','OK','ERR value not in allowed values: [a, b]','a'])
  self.assertEqual(run(['DEFINE e TYPE string PATTERN "^[a-z]+@[a-z]+$"','SET e x@y','VALIDATE e']),['OK','OK','OK'])
 def test_negative_ranges_and_indices(self):
  self.assertEqual(run(['SET a abcdef','GETRANGE a -3 -1','GETRANGE a 10 20','GETRANGE a -99 -99','RPUSH l a b','LINDEX l -1','LRANGE l 2 1']),['OK','def','','','2','b','(empty list)'])
 def test_fresh_instances(self):self.assertEqual(run(['GET a']),['(nil)'])
if __name__=='__main__':unittest.main()
