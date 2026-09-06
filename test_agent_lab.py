import unittest,random,json
from agent_engine import validate_suite,evaluate,feedback,merge,APIClient
from agent_lab import shrink_sequence,shrink_relation
from heldout_target import MUTANTS,run as heldout_run
from local_target import run

WITNESSES={
'decrby_sign':(['SET a 10','DECRBY a 3'],['OK','7']),
'mget_reorders':(['MSET a x b y','MGET b a'],['OK','y\nx']),
'lindex_negative_offone':(['RPUSH l a b','LINDEX l -1'],['2','b']),
'rpop_wrong_end':(['RPUSH l a b','RPOP l'],['2','b']),
'exists_deduplicates':(['SET a x','EXISTS a a'],['OK','2']),
'mset_loses_last':(['MSET a x b y','GET b'],['OK','y']),
'append_returns_old_length':(['SET a x','APPEND a y'],['OK','2']),
'expr_mod_sign':(['EVAL (% -7 3)'],['-1']),
}
class AgentLabTests(unittest.TestCase):
 def test_holdout_witnesses(self):
  self.assertEqual(set(WITNESSES),set(MUTANTS))
  for m,(s,e) in WITNESSES.items():
   self.assertEqual(run(s),e);self.assertNotEqual(heldout_run(s,m),e)
 def test_validator_limits(self):
  bad=[{'sequences':[['GET a\nDEL a']]},{'sequences':[['import os']]},{'sequences':[['DEFINE a TYPE string PATTERN "(a+)+$"']]},{'sequences':[['GET a','GET a']]},{'relations':[{'a':['GET a'],'b':['GET a'],'relation':'MAYBE'}]}]
  for x in bad:
   with self.assertRaises(ValueError):validate_suite(x,1)
 def test_invalid_relations_not_counted_as_kills(self):
  s=validate_suite({'relations':[{'a':['SET a 1','GET a'],'b':['SET a 2','GET a'],'relation':'EQ'}]},4)
  e=evaluate(s);self.assertEqual(e['detected'],0);self.assertEqual(e['invalid_relation_indices'],[0])
 def test_feedback_does_not_expose_mutant_names(self):
  from local_target import MUTANTS as dev
  f=json.dumps(feedback(validate_suite({'sequences':[['GET a']]},1)))
  self.assertFalse(any(m in f for m in dev+MUTANTS))
 def test_minimization(self):
  small,n,minimal=shrink_sequence(['SET b z','SET a 10','DECRBY a 3'],'decrby_sign',heldout_run)
  self.assertTrue(minimal);self.assertNotEqual(run(small),heldout_run(small,'decrby_sign'))
  for i in range(len(small)):
   c=small[:i]+small[i+1:];self.assertEqual(run(c),heldout_run(c,'decrby_sign'))
 def test_relation_minimization(self):
  r={'a':['SET b z','SET a 10','DECRBY a 3'],'b':['SET a 7','GET a'],'relation':'EQ'}
  small,n,minimal=shrink_relation(r,'decrby_sign',heldout_run)
  from agent_engine import relation_ok
  self.assertTrue(minimal);self.assertTrue(relation_ok(small,run));self.assertFalse(relation_ok(small,lambda s:heldout_run(s,'decrby_sign')))
 def test_api_cap_before_network(self):
  c=object.__new__(APIClient);c.attempts=3;c.max_calls=3
  with self.assertRaises(RuntimeError):c.generate(20)
if __name__=='__main__':unittest.main()

class ProtocolTests(unittest.TestCase):
 def client(self):
  c=object.__new__(APIClient);c.record={'url':'https://example.invalid','key':'test-not-a-real-key'};c.model='test';c.max_calls=3;c.attempts=0;c.usage=[];return c
 def test_bad_json_keeps_usage_and_does_not_retry(self):
  from unittest.mock import patch,MagicMock
  payload={'model':'test','usage':{'total_tokens':17},'choices':[{'finish_reason':'stop','message':{'content':'not json'}}]}
  response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(payload).encode()
  c=self.client()
  with patch('agent_engine.urllib.request.urlopen',return_value=response) as call:
   with self.assertRaises(RuntimeError):c.generate(20)
  self.assertEqual(call.call_count,1);self.assertEqual(c.usage[0]['usage']['total_tokens'],17);self.assertEqual(c.usage[0]['status'],'failed')
 def test_truncation_rejected_even_if_json_parseable(self):
  from unittest.mock import patch,MagicMock
  payload={'usage':{'total_tokens':20},'choices':[{'finish_reason':'length','message':{'content':'{"sequences":[["GET a"]]}'}}]}
  response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(payload).encode()
  c=self.client()
  with patch('agent_engine.urllib.request.urlopen',return_value=response):
   with self.assertRaises(RuntimeError):c.generate(20)
 def test_http_error_body_not_retained(self):
  from unittest.mock import patch
  from urllib.error import HTTPError
  import io
  c=self.client()
  with patch('agent_engine.urllib.request.urlopen',side_effect=HTTPError('https://example.invalid',401,'secret error',{},io.BytesIO(b'secret error'))):
   with self.assertRaises(RuntimeError) as e:c.generate(20)
  self.assertNotIn('secret error',str(e.exception)+json.dumps(c.usage));self.assertEqual(c.usage[0]['http_status'],401)
 def test_saved_run_replay(self):
  from pathlib import Path
  from replay_lab import replay
  p=Path(__file__).parent/'examples/recorded-run.json'
  if p.exists():self.assertEqual(replay(p)['status'],'PASS')
