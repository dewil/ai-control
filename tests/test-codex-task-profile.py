#!/usr/bin/env python3
"""Blind contract tests for CXTASK-SEALED; no native calls/config reads."""
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
import tempfile
import tomllib
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'bin/_codex_task_profile.py'
sys.path.insert(0, str(MODULE.parent))
SPEC = importlib.util.spec_from_file_location('profile_under_test', MODULE)
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)

FALSE_FEATURES = 'shell_tool js_repl js_repl_tools_only code_mode_only multi_agent multi_agent_v2 hooks plugins remote_plugin apps tool_suggest request_permissions_tool image_generation view_image deferred_executor token_budget current_time_reminder sleep_tool send_message_to_user_async browser_use browser_use_full_cdp_access browser_use_external computer_use memories goals agent_message_board skill_search'.split()
NAMES = ['task_read','task_search','task_list','task_ask','task_done']
REGISTRY = ['apply_patch','clock__curr_time'] + NAMES
HASHES = {
 'codex':'12eb3e81114588aca3b7998f4f19e8997b056aca08e57a7ca7c8a3ec8c652aad',
 'code_mode_host':'37cab1584302611e9936902219640ab5e7a79fcfccd2504c6e85ea8cb97d0e10',
 'bwrap':'01fb705f067bd5365b63d8ad2323a61c8d007733ca5e649437e086f3fb9935d8',
 'rg':'e62198eb19b136b88c330af83647b5a962cb99b6b1f066758568f12de1974849'}

def descriptors():
 return [{'type':'function','deferLoading':False,'name':n,'description':'Bounded task tool','inputSchema':{'type':'object','properties':{'value':{'type':'string'}},'required':[],'additionalProperties':False}} for n in NAMES]

def nested(flat):
 result={}
 for key,value in flat.items():
  node=result
  parts=key.split('.')
  for part in parts[:-1]: node=node.setdefault(part,{})
  node[parts[-1]]=copy.deepcopy(value)
 return result

class ProfileTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='sealed-tests-')
  self.root=Path(self.tmp.name)
  self.cwd=self.root/'work[$]`quoted*?'
  self.cwd.mkdir(mode=0o700)
  (self.cwd/'.git').write_text('gitdir: harmless placeholder\n')
  self.c=str(self.cwd)
  self.socket=str(self.root/'socket')
 def tearDown(self): self.tmp.cleanup()
 def reject(self,fn,*args,**kwargs):
  with self.assertRaises(p.ProfileError) as error: fn(*args,**kwargs)
  msg=str(error.exception)
  self.assertNotIn(self.c,msg)
  self.assertNotIn('SECRET_MARKER',msg)
 def evidence(self):
  cfg=nested(p.sealed_overrides(self.c,['inventory']))
  response={'thread':{'id':'12345678-1234-4234-8234-123456789abc','cwd':self.c,'ephemeral':False,'environments':[{'environmentId':'local','cwd':self.c,'runtimeWorkspaceRoots':[self.c]}]},'cwd':self.c,'runtimeWorkspaceRoots':[self.c],'model':'inherited-model','reasoningEffort':None,'approvalPolicy':'on-request','approvalsReviewer':'user','activePermissionProfile':{'id':'control_task','extends':None},'sandbox':{'type':'workspaceWrite','networkAccess':False,'excludeTmpdirEnvVar':True,'excludeSlashTmp':True,'writableRoots':[self.c]}}
  pages=[{'data':[{'name':'inventory','runtimeStatus':'disabled','tools':{},'resources':[],'resourceTemplates':[]}],'nextCursor':None}]
  return [response,self.c,cfg,pages,REGISTRY[:],{'version':'0.160.0','hashes':HASHES.copy()}]
 def test_fixed_overrides_and_fresh_outputs(self):
  o=p.sealed_overrides(self.c,['inventory'])
  for name in FALSE_FEATURES: self.assertIs(o['features.'+name],False,name)
  self.assertEqual(o['features.code_mode'],{'enabled':False,'direct_only_tool_namespaces':[],'excluded_tool_namespaces':[]})
  self.assertEqual(o['features.code_mode_host'],{'enabled':True,'disable_in_process_fallback':False})
  self.assertIs(o['features.code_mode_interrupt'],True)
  for k in ['agents.enabled','tools.experimental_request_user_input.enabled','tools.update_plan.enabled','memories.use_memories','cloud.skills.enabled','mcp_servers.inventory.enabled']: self.assertIs(o[k],False)
  self.assertEqual(o['notify'],[]); self.assertEqual(o['web_search'],'disabled')
  self.assertEqual(o['default_permissions'],'control_task')
  self.assertFalse(any(k in o for k in ['model','model_reasoning_effort','profile','model_provider']))
  o['notify'].append('mutated'); self.assertEqual(p.sealed_overrides(self.c,[])['notify'],[])
 def test_globs_casefold_and_literal_root(self):
  fs=p.sealed_overrides(self.c,[])['permissions.control_task']['filesystem']
  self.assertEqual(fs['/'],'deny'); self.assertEqual(fs[self.c],'write'); self.assertEqual(fs[self.c+'/.git'],'deny')
  prefix=self.c.replace('\\','\\\\').replace('[','\\[').replace(']','\\]').replace('*','\\*').replace('?','\\?')+'/**/'
  fold=lambda s: ''.join('['+x.lower()+x.upper()+']' if x.isascii() and x.isalpha() else x for x in s)
  for name in ['.env','.env.*','.netrc','.npmrc','.pypirc','auth.json','credentials.json','cookies.json','id_rsa','id_ed25519','id_dsa','id_ecdsa','*.pem','*.key','*.p12','*.pfx']:
   self.assertEqual(fs[prefix+fold(name)],'deny',name)
  for name in ['.git','.ssh','.aws','.azure','.kube','browser-sessions']:
   self.assertEqual(fs[prefix+fold(name)],'deny'); self.assertEqual(fs[prefix+fold(name)+'/**'],'deny')
  self.assertEqual(p.sealed_overrides(self.c,[])['permissions.control_task']['network'],{'enabled':False})
 def test_host_toml_roundtrip_not_shell(self):
  argv=p.sealed_host_argv(self.socket,self.c,['inventory'],executable='/opt/codex$`literal')
  self.assertEqual(argv[:4],['/opt/codex$`literal','app-server','--listen','unix://'+self.socket])
  self.assertEqual(len(argv[4:])%2,0)
  parsed={}
  def merge(a,b):
   for k,v in b.items():
    if isinstance(v,dict) and k in a: merge(a[k],v)
    else: self.assertNotIn(k,a); a[k]=v
  for flag,assignment in zip(argv[4::2],argv[5::2]):
   self.assertEqual(flag,'-c'); merge(parsed,tomllib.loads(assignment))
  self.assertEqual(parsed,nested(p.sealed_overrides(self.c,['inventory'])))
 def test_host_cli_literal_dotted_keys_and_toml_values(self):
  argv=p.sealed_host_argv(self.socket,self.c,['inventory'])
  expected=p.sealed_overrides(self.c,['inventory'])
  actual={}
  for flag,assignment in zip(argv[4::2],argv[5::2]):
   self.assertEqual(flag,'-c')
   key,separator,value=assignment.partition('=')
   self.assertEqual(separator,'=')
   self.assertIn(key,expected)
   self.assertNotIn(key,actual)
   actual[key]=tomllib.loads('_x_='+value)['_x_']
  self.assertEqual(actual,expected)
 def test_thread_exact_shape_and_deepcopy(self):
  tools=descriptors(); before=copy.deepcopy(tools)
  v=p.sealed_thread_params(self.c,['inventory'],tools)
  self.assertEqual(v,{'cwd':self.c,'runtimeWorkspaceRoots':[self.c],'ephemeral':False,'permissions':'control_task','approvalPolicy':'on-request','approvalsReviewer':'user','selectedCapabilityRoots':[],'environments':[{'environmentId':'local','cwd':self.c,'runtimeWorkspaceRoots':[self.c]}],'config':p.sealed_overrides(self.c,['inventory']),'dynamicTools':before})
  v['dynamicTools'][0]['inputSchema']['properties']['new']={}; self.assertEqual(tools,before)
 def test_metadata_invalid_roots_git_and_socket(self):
  for c in [self.c+'/.',str(self.root/'missing'),'relative',None]: self.reject(p.sealed_overrides,c,[])
  link=self.root/'link'; link.symlink_to(self.cwd,target_is_directory=True); self.reject(p.sealed_overrides,str(link),[])
  git=self.cwd/'.git'; git.unlink(); self.reject(p.sealed_overrides,self.c,[])
  git.mkdir(); self.reject(p.sealed_overrides,self.c,[]); git.rmdir()
  git.symlink_to(self.root/'missing'); self.reject(p.sealed_overrides,self.c,[]); git.unlink()
  git.write_text('placeholder'); os.link(git,self.root/'hardlink'); self.reject(p.sealed_overrides,self.c,[])
  for sock in ['relative',self.socket+'/../socket',self.c]: self.reject(p.sealed_host_argv,sock,self.c,[])
 def test_plain_types_mcp_and_executable(self):
  class Spoof(str): pass
  for names in [('a',),['a','a'],['a.b'],['SECRET_MARKER!'],[Spoof('a')],[1]]: self.reject(p.sealed_overrides,self.c,names)
  self.reject(p.sealed_overrides,Spoof(self.c),[])
  for exe in ['', 'x\x00y','x\ny',Spoof('codex')]: self.reject(p.sealed_host_argv,self.socket,self.c,[],executable=exe)
 def test_descriptor_refusals(self):
  variants=[]
  variants.extend([descriptors()[:-1],descriptors()+[descriptors()[0]]])
  for missing in ['type','deferLoading']:
   x=descriptors(); del x[0][missing]; variants.append(x)
  for field,value in [('namespace','x'),('deferLoading',True),('type','legacy'),('description',''),('description','x'*4097)]:
   x=descriptors(); x[0][field]=value; variants.append(x)
  for field,value in [('type','array'),('additionalProperties',True),('required',['unknown'])]:
   x=descriptors(); x[0]['inputSchema'][field]=value; variants.append(x)
  x=descriptors(); x[0]['inputSchema']['properties']['bad']={'enum':[float('nan')]}; variants.append(x)
  x=descriptors(); x[0]['inputSchema']['properties']['big']={'enum':['x'*66000]}; variants.append(x)
  class Dict(dict): pass
  x=descriptors(); x[0]=Dict(x[0]); variants.append(x)
  for tools in variants: self.reject(p.sealed_thread_params,self.c,[],tools)
 def test_accepts_controller_evidence_without_mutation(self):
  args=self.evidence(); before=copy.deepcopy(args)
  self.assertEqual(p.validate_sealed_policy(*args),{'thread_id':'12345678-1234-4234-8234-123456789abc','model':'inherited-model','reasoning_effort':None,'permission_profile':'control_task'})
  self.assertEqual(args,before)
 def test_policy_profile_environment_roots_refusals(self):
  mutations=[lambda r:r.update(activePermissionProfile={'id':'other','extends':None}),lambda r:r.update(activePermissionProfile={'id':'control_task','extends':'parent'}),lambda r:r['thread'].update(environments=[]),lambda r:r['thread']['environments'].append({'environmentId':'remote'}),lambda r:r.update(runtimeWorkspaceRoots=[]),lambda r:r.update(approvalsReviewer='guardian'),lambda r:r['sandbox'].update(networkAccess=True),lambda r:r['sandbox'].update(type='readOnly'),lambda r:r['sandbox'].update(writableRoots=['/']),lambda r:r['thread'].update(id='not-uuid')]
  for mutate in mutations:
   a=self.evidence(); mutate(a[0]); self.reject(p.validate_sealed_policy,*a)
 def test_config_mismatches_and_documented_api_exceptions(self):
  for feature in FALSE_FEATURES:
   a=self.evidence(); a[2]['features'][feature]=True; self.reject(p.validate_sealed_policy,*a)
  for mutate in [lambda c:c.update(notify=['SECRET_MARKER']),lambda c:c.update(default_permissions='other'),lambda c:c['permissions']['control_task']['filesystem'].update({'/':'read'}),lambda c:c['permissions']['control_task'].update(extends='other'),lambda c:c['mcp_servers'].update(other={'enabled':True}),lambda c:c['features']['code_mode_host'].update(enabled=False),lambda c:c['features']['code_mode'].update(excluded_tool_namespaces=['x'])]:
   a=self.evidence(); mutate(a[2]); self.reject(p.validate_sealed_policy,*a)
  a=self.evidence(); del a[2]['tools']['experimental_request_user_input']; del a[2]['tools']['update_plan']; p.validate_sealed_policy(*a)
  a=self.evidence(); a[2]['unrelated']={'safe':'value'}; p.validate_sealed_policy(*a)
  for key in ['experimental_request_user_input','update_plan']:
   a=self.evidence(); a[2]['tools'][key]['enabled']=True; self.reject(p.validate_sealed_policy,*a)
  a=self.evidence(); del a[2]['features']['shell_tool']; self.reject(p.validate_sealed_policy,*a)
 def test_catalog_completeness(self):
  for pages in [[],[{'data':[],'nextCursor':'more'}],[{'data':[{'name':'inventory','runtimeStatus':'starting','tools':{},'resources':[],'resourceTemplates':[]}],'nextCursor':None}]]:
   a=self.evidence(); a[3]=pages; self.reject(p.validate_sealed_policy,*a)
 def test_native_typed_profile_known_null_projection(self):
  a=self.evidence()
  profile=a[2]['permissions']['control_task']
  profile.update(description=None,extends=None,workspace_roots=None)
  profile['filesystem']['glob_scan_max_depth']=None
  network_fields='proxy_url enable_socks5 socks_url enable_socks5_udp allow_upstream_proxy dangerously_allow_non_loopback_proxy dangerously_allow_all_unix_sockets mode domains unix_sockets allow_local_binding mitm'.split()
  profile['network'].update({key:None for key in network_fields})
  before=copy.deepcopy(a)
  p.validate_sealed_policy(*a)
  self.assertEqual(a,before)
  for target,key in [('profile','description'),('profile','extends'),('profile','workspace_roots'),('filesystem','glob_scan_max_depth')]+[('network',key) for key in network_fields]:
   b=copy.deepcopy(a); row=b[2]['permissions']['control_task']
   if target!='profile': row=row[target]
   row[key]=False
   self.reject(p.validate_sealed_policy,*b)
  for target in ['profile','filesystem','network']:
   b=copy.deepcopy(a); row=b[2]['permissions']['control_task']
   if target!='profile': row=row[target]
   row['unknown_projection_field']=None
   self.reject(p.validate_sealed_policy,*b)
 def test_catalog_names_equal_observed_config(self):
  a=self.evidence(); a[3]=[{'data':[],'nextCursor':None}]; self.reject(p.validate_sealed_policy,*a)
  a=self.evidence(); a[3][0]['data'].append({'name':'extra','runtimeStatus':'disabled','tools':{},'resources':[],'resourceTemplates':[]}); self.reject(p.validate_sealed_policy,*a)
  a=self.evidence(); a[2]['mcp_servers']['dormant']={'enabled':False}; self.reject(p.validate_sealed_policy,*a)
  a=self.evidence(); a[2]['mcp_servers']={}; a[3]=[{'data':[],'nextCursor':None}]; p.validate_sealed_policy(*a)
 def test_nested_flags_reject_numeric_boolean_spoof(self):
  for mutate in [lambda c:c['features'].update(shell_tool=0),lambda c:c['features'].update(code_mode_interrupt=1),lambda c:c['features']['code_mode_host'].update(enabled=1),lambda c:c['features']['code_mode_host'].update(disable_in_process_fallback=0),lambda c:c['permissions']['control_task']['network'].update(enabled=0),lambda c:c['agents'].update(enabled=0),lambda c:c['mcp_servers']['inventory'].update(enabled=0),lambda c:c['tools']['update_plan'].update(enabled=0)]:
   a=self.evidence(); mutate(a[2]); self.reject(p.validate_sealed_policy,*a)
 def test_registry_and_release_refusals(self):
  for registry in [REGISTRY[:-1],REGISTRY+['exec_command'],REGISTRY+['clock__curr_time'],tuple(REGISTRY)]:
   a=self.evidence(); a[4]=registry; self.reject(p.validate_sealed_policy,*a)
  for mutate in [lambda e:e.update(version='0.159.0'),lambda e:e.update(extra=True),lambda e:e['hashes'].update(codex='0'*64),lambda e:e['hashes'].update(rg=HASHES['rg'].upper()),lambda e:e['hashes'].pop('bwrap'),lambda e:e['hashes'].update(extra='0'*64)]:
   a=self.evidence(); mutate(a[5]); self.reject(p.validate_sealed_policy,*a)
 def test_evidence_rejects_subclasses_and_non_json(self):
  class List(list): pass
  class String(str): pass
  class Dict(dict): pass
  for index,value in [(0,Dict(self.evidence()[0])),(4,List(REGISTRY)),(4,[String(x) for x in REGISTRY]),(5,Dict(self.evidence()[5]))]:
   a=self.evidence(); a[index]=value; self.reject(p.validate_sealed_policy,*a)
  a=self.evidence(); a[2]['unrelated']=float('inf'); self.reject(p.validate_sealed_policy,*a)

if __name__=='__main__': unittest.main()
