"""Measure the feasibility of matching catalog characteristics before KTRU retrieval.

Reads all actual XML parts and all workbook rows without modifying sources.
Writes docs/characteristic-first-audit.json. Uses only the standard library and
the existing profile_data workbook reader. Run from any working directory.
Counts and collision checks describe the supplied snapshot, not model quality.
"""

import sys
import json
import re
import statistics
from pathlib import Path
from collections import Counter, defaultdict
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from profile_data import workbook_rows, txt, nodes, normalize, O

def norm(s):
    return normalize(s)

def canonical(node):
    return (node.tag.rsplit('}', 1)[-1], norm(node.text or ''), tuple(sorted(canonical(c) for c in node if c.tag != O+'valueCode')))

def bucket():
    return dict(positions=0, char_occurrences=0, value_occurrences=0, names=set(), definitions=set(), categorical_facts=set(), numeric_rules=set(), name_frequency=Counter(), char_counts=[], no_chars=0, no_new_features=0, fingerprints=defaultdict(list), name_fingerprints=defaultdict(list), codes=defaultdict(set), units=defaultdict(set), dates=Counter())

groups={k:bucket() for k in ('all_actual_records','active_specific','clothing_rubric_116','furniture_rubric_128','tools_prefix_25.73_or_28.24')}
examples=[]
seen=set()
for fi,path in enumerate(sorted((ROOT/'data').rglob('*all_actual*.xml')),1):
    stack=[]
    for event,e in ET.iterparse(path,events=('start','end')):
        if event=='start':
            stack.append(e)
            continue
        if e.tag != O+'position':
            stack.pop()
            continue
        d=e.find(O+'data')
        code,version,name=txt(d,'code'),txt(d,'version'),txt(d,'name')
        key=(code,version)
        scopes=['all_actual_records']
        active=txt(d,'status')=='ACTIVE' and txt(d,'isTemplate')=='false'
        if active and key not in seen:
            scopes.append('active_specific')
            rubrics={txt(r,'code') for r in nodes(d,'rubricators/rubricatorInfo')}
            if '116' in rubrics: scopes.append('clothing_rubric_116')
            if '128' in rubrics: scopes.append('furniture_rubric_128')
            if code.startswith(('25.73.','28.24.')): scopes.append('tools_prefix_25.73_or_28.24')
            seen.add(key)
        chars=[]
        for c in nodes(d,'characteristics/characteristic'):
            if txt(c,'actual')=='false': continue
            vals=nodes(c,'values/value')
            cn=norm(txt(c,'name'))
            units=tuple(sorted({txt(v,'OKEI/code') for v in vals}))
            definition=(cn,txt(c,'type'),units)
            cf=[]; nr=[]
            for v in vals:
                qual=txt(v,'qualityDescription')
                if qual: cf.append((cn,norm(qual),txt(v,'OKEI/code')))
                if v.find(O+'rangeSet') is not None or v.find(O+'valueSet') is not None:
                    nr.append((cn,canonical(v)))
            fingerprint=(definition,txt(c,'kind'),txt(c,'isRequired'),tuple(sorted(canonical(v) for v in vals)))
            chars.append(dict(name=cn,code=txt(c,'code'),definition=definition,units=units,cf=cf,nr=nr,fingerprint=fingerprint,value_count=len(vals),raw_name=txt(c,'name')))
        fp=tuple(sorted(c['fingerprint'] for c in chars))
        for scope in scopes:
            b=groups[scope]
            b['positions']+=1
            b['char_counts'].append(len(chars))
            b['no_chars']+=not chars
            b['no_new_features']+=txt(d,'noNewFeatures')=='true'
            b['dates']['start_after_2026_10_10']+=txt(d,'applicationDateStart')[:10]>'2026-10-10'
            b['dates']['end_before_2026_10_10']+=bool(txt(d,'applicationDateEnd')) and txt(d,'applicationDateEnd')[:10]<'2026-10-10'
            for c in chars:
                b['char_occurrences']+=1
                b['value_occurrences']+=c['value_count']
                b['names'].add(c['name'])
                b['definitions'].add(c['definition'])
                b['categorical_facts'].update(c['cf'])
                b['numeric_rules'].update(c['nr'])
                b['name_frequency'][c['name']]+=1
                b['codes'][c['code']].add(c['name'])
                b['units'][c['name']].update(c['units'])
            if scope!='all_actual_records':
                b['fingerprints'][fp].append((code,name))
                b['name_fingerprints'][(norm(name),fp)].append((code,name))
        if active and (name=='Дрель ручная электрическая' or (len(scopes)>2 and not chars and len(examples)<8)):
            examples.append(dict(code=code,version=version,name=name,file=path.name,noNewFeatures=txt(d,'noNewFeatures'),chars=[dict(name=txt(c,'name'),kind=txt(c,'kind'),required=txt(c,'isRequired'),values=[ET.tostring(v,encoding='unicode') for v in nodes(c,'values/value')]) for c in nodes(d,'characteristics/characteristic')]))
        if len(stack)>1:stack[-2].remove(e)
        e.clear();stack.pop()
    if fi%20==0: print(f'XML {fi}/82',flush=True)

def summarize(b):
    counts=sorted(b['char_counts'])
    collisions=[v for k,v in b['fingerprints'].items() if k and len(v)>1]
    same_name=[v for (n,k),v in b['name_fingerprints'].items() if k and len(v)>1]
    return dict(positions=b['positions'],characteristic_occurrences=b['char_occurrences'],value_occurrences=b['value_occurrences'],normalized_names=len(b['names']),name_type_units_definitions=len(b['definitions']),unique_categorical_facts=len(b['categorical_facts']),unique_numeric_rules=len(b['numeric_rules']),without_characteristics=b['no_chars'],no_new_features=b['no_new_features'],characteristics_per_position=dict(median=statistics.median(counts) if counts else 0,p95=counts[int((len(counts)-1)*.95)] if counts else 0,max=max(counts,default=0)),top_names=b['name_frequency'].most_common(12),codes_with_multiple_normalized_names=sum(len(v)>1 for v in b['codes'].values()),names_with_multiple_nonempty_unit_codes=sum(len(v-{''})>1 for v in b['units'].values()),duplicate_nonempty_constraint_groups=len(collisions),positions_in_duplicate_nonempty_constraint_groups=sum(map(len,collisions)),same_name_and_constraints_groups=len(same_name),same_name_and_constraints_positions=sum(map(len,same_name)),same_name_and_constraints_examples=same_name[:5],constraint_collision_examples=collisions[:3],date_flags=dict(b['dates']))

out={'scope_note':'all_actual includes terminated/templates; other groups deduplicate ACTIVE non-template (code,version), before lifecycle/date review. Rubrics and tool prefixes are explicit exploratory subsets, not a complete reviewed domain mapping. Constraint fingerprints ignore identifiers/order and normalize case/whitespace/ё, but retain units, types, kind, required and value rules. Fingerprint comparisons are not computed for all_actual_records; name/type/unit keys are lexical grouping keys, not proven semantic equivalence.','ktru':{k:summarize(b) for k,b in groups.items()},'examples':examples,'workbooks':{}}
for field in ('duplicate_nonempty_constraint_groups','positions_in_duplicate_nonempty_constraint_groups','same_name_and_constraints_groups','same_name_and_constraints_positions','same_name_and_constraints_examples','constraint_collision_examples'):
    out['ktru']['all_actual_records'][field]=None
out['ktru_subset_union']={key:len(set().union(*(groups[g][key] for g in ('clothing_rubric_116','furniture_rubric_128','tools_prefix_25.73_or_28.24')))) for key in ('names','definitions','categorical_facts','numeric_rules')}
all_excel_names=set();all_excel_defs=set()
for path in sorted((ROOT/'data').rglob('*.xlsx')):
    raw_names=set();names=set();defs=set();val_pairs=set();types=Counter();categories=set();bad=0;valid=0;rows=0;ste=0;headings={};samples=[];name_units=defaultdict(set);category_names=defaultdict(set);category_labels={};name_examples=[]
    for sheet,row_no,row in workbook_rows(path):
        if sheet not in headings:
            headings[sheet]=row
            continue
        if not row:continue
        if headings[sheet].get('A')=='ID СТЕ':
            ste+=1
            if len(samples)<2:samples.append({'row':row_no,'id':row.get('A'),'name':row.get('B'),'characteristics':row.get('F','')[:1800]})
            continue
        rows+=1
        if not re.fullmatch(r'\d{2}(?:\.\d{2})+',row.get('B','')) or row.get('E') not in {'Базовая','Эталонная','Категореобразующая'} or not row.get('D') or not row.get('F'):
            bad+=1;continue
        valid+=1
        n=norm(row['D']);t=norm(row['F']);u=norm(row.get('H',''))
        raw_names.add(row['D']);names.add(n);defs.add((n,t,u));types[t]+=1;categories.add(row.get('B'))
        category_names[row.get('B')].add(n)
        category_labels[row.get('B')]=row.get('A')
        if len(n)>100 and len(name_examples)<5:name_examples.append({'row':row_no,'name':row['D'],'type':row['F'],'unit':row.get('H','')})
        name_units[n].add(u)
        for v in row.get('G','').split('|'):
            v=norm(v)
            if v and '[не найдено значение id:' not in v:val_pairs.add((n,t,u,v))
    all_excel_names.update(names);all_excel_defs.update(defs)
    sizes=sorted(map(len,category_names.values()))
    out['workbooks'][path.stem]=dict(ste_rows=ste,template_rows=rows,valid_rows=valid,invalid_rows=bad,raw_names=len(raw_names),normalized_names=len(names),name_type_unit_definitions=len(defs),raw_pipe_split_value_candidates=len(val_pairs),types=dict(types),categories=len(categories),properties_per_category=dict(median=statistics.median(sizes),max=max(sizes)),name_overlap_all_ktru=len(names&groups['all_actual_records']['names']),name_overlap_active_specific=len(names&groups['active_specific']['names']),ste_samples=samples)
    out['workbooks'][path.stem]['largest_categories']=[{'code':k,'name':category_labels[k],'names':len(v)} for k,v in sorted(category_names.items(),key=lambda kv:len(kv[1]),reverse=True)[:3]]
    out['workbooks'][path.stem]['long_property_name_examples']=name_examples
    print(f'Workbook {path.name} done',flush=True)
out['excel_union']={'normalized_names':len(all_excel_names),'name_type_unit_definitions':len(all_excel_defs),'overlap_all_ktru':len(all_excel_names&groups['all_actual_records']['names']),'overlap_active_specific':len(all_excel_names&groups['active_specific']['names'])}
out['combined_union_normalized_names']=len(all_excel_names|groups['active_specific']['names'])
dest=ROOT/'docs'/'characteristic-first-audit.json'
dest.parent.mkdir(exist_ok=True)
dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k!='examples'},ensure_ascii=False,indent=2),flush=True)
print('Saved',dest,flush=True)
