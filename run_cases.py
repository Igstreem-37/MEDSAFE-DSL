import subprocess, json, sys
import os; SRC=os.path.dirname(os.path.abspath(__file__))
# (id, category, file, extra args, expected exit, expected substring, expectation text)
C=[
("TC1","Valid","valid.smed",[],0,"COMPILATION SUCCESSFUL","Compiles; all checks SAFE"),
("TC2","Valid","phase3_demo.smed",[],0,"no alarms","Safe protocol; no runtime alarms"),
("TC3","Valid","phase3_demo.smed",["--strict"],0,"no alarms","--strict with no alarms exits 0"),
("TC4","Syntax error","syntax_error.smed",[],1,"Syntax","Rejected with a syntax error"),
("TC5","Semantic error","semantic_error.smed",[],1,"Semantic Error","Rate above the drug limit rejected"),
("TC6","Multi-drug error","multidrug_error.smed",[],1,"Semantic Error","One drug in a multi-drug infusion exceeds its limit"),
("TC7","Conditional error","conditional_error.smed",[],1,"Semantic Error","Chosen weight branch exceeds the limit"),
("TC8","Repeat error","repeat_error.smed",[],1,"Semantic Error","REPEAT dose above the limit rejected"),
("TC9","Cumulative error","cumulative_error.smed",[],1,"exceeding MAX_TOTAL","Cumulative dose 60 mg > MAX_TOTAL 40 mg"),
("TC10","Interaction error","interaction_error.smed",[],1,"INTERACTION limit","Combined 15 mg/hr > limit 12 mg/hr"),
("TC11","OVER error","over_error.smed",[],1,"longer than its EVERY","OVER 6 hr > EVERY 4 hr rejected"),
("TC12","Runtime hazard","phase3_alarm_demo.smed",[],0,"1 ALARM","Passes static checks; runtime TOTAL alarm (288 mg > 150 mg)"),
("TC13","Runtime hazard","phase3_alarm_demo.smed",["--strict"],2,"1 ALARM","--strict returns exit code 2"),
("TC14","Runtime hazard","phase3_alarm_demo.smed",[],0,"t=12.500hr","Cumulative crossing at exactly 12.5 hr (150 / 12)"),
("TC15","Phase 3.1 error","phase2_demo.smed",[],1,"concurrent infusions of","Same-drug sum 10 + 18 + 10 = 38 > 20 mg/hr rejected statically"),
("TC16","Phase 3.1 error","concurrent_error.smed",[],1,"24.000 mg/hr at t=0hr","Infusion + bolus of same drug 12 + 12 = 24 > 20 rejected"),
("TC17","Phase 3.1 valid","phase31_demo.smed",[],0,"CONCURRENT  p1/dopamine: peak 18.000","Same-drug peak exactly 18 mg/hr <= 20; VM agrees, no alarms"),
("TC18","Phase 3.2 valid","phase32_demo.smed",[],0,"INTERACTION p1/dopamine+heparin: 20.000","Bounded infusion total 80 mg proven; interaction with a REPEAT dose peaks exactly at limit"),
("TC19","Phase 3.2 error","bounded_total_error.smed",[],1,"after infusion 'run'","Bounded infusion 12 x 10 = 120 mg > MAX_TOTAL 100 mg rejected statically"),
("TC20","Phase 3.2 error","interaction_repeat_error.smed",[],1,"at t=0hr, exceeding the INTERACTION","Infusion + REPEAT dose 5 + 15 = 20 > 18 mg/hr rejected statically"),
]
rows=[]
for cid,cat,f,args,ex,sub,txt in C:
    r=subprocess.run([sys.executable,"main.py",f]+args,cwd=SRC,capture_output=True,text=True)
    out=r.stdout+r.stderr
    ok=(r.returncode==ex and sub in out)
    rows.append(dict(id=cid,cat=cat,file=f,args=" ".join(args),exp=txt,exp_exit=ex,act_exit=r.returncode,ok=ok))
json.dump(rows,open('cases_result.json','w'),indent=1)
for r in rows: print(r['id'],r['file'],r['args'],'exit',r['act_exit'],'PASS' if r['ok'] else 'FAIL')
