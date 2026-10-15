"""Read optional startup traces (and old exit traces); never launch the saver."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def read_traces(folder):
    traces=[]
    for path in sorted([*Path(folder).glob('startup_trace_*.jsonl'), *Path(folder).glob('exit_trace_*.jsonl')]):
        rows=[]
        try:
            for line in path.read_text(encoding='utf-8-sig',errors='replace').splitlines():
                try: rows.append(json.loads(line))
                except (ValueError,TypeError): continue
        except OSError: continue
        context=next((r for r in rows if r.get('event')=='process_context' and r.get('reason')=='startup'),{})
        process=context.get('process',{})
        traces.append(dict(file=path.name, rows=rows, pid=process.get('pid'),
                           created=process.get('creation_filetime'), parent=context.get('parent',{})))
    return traces


def points(trace, name):
    return [r for r in trace['rows'] if r.get('event')=='startup_point' and r.get('name')==name]


def elapsed(root, event):
    """OS start to entry uses wall time; remaining interval uses monotonic time."""
    if not root or not event or not root.get('created'): return None
    entry=next((r for r in root['rows'] if r.get('event')=='process_entry'),None)
    if not entry:return None
    try:
        created=datetime(1601,1,1,tzinfo=timezone.utc)+timedelta(microseconds=root['created']//10)
        initial=(datetime.fromisoformat(entry['time'])-created).total_seconds()
        return round(initial+event['monotonic']-entry['monotonic'],6)
    except (KeyError,TypeError,ValueError):return None


def summarize(traces):
    indexed={(t['pid'],t['created']):t for t in traces if t['created']}
    result=[]
    for worker in traces:
        layouts=points(worker,'layout')
        if not layouts:continue
        layout=layouts[0]; parent=worker['parent']
        root=indexed.get((parent.get('pid'),parent.get('creation_filetime')))
        if root is None and any(r.get('role')=='host' for r in worker['rows']):root=worker
        expected=int(layout['slots']); first={}; child_rows=[]; missing=[]
        if layout['independent']:
            starts=points(worker,'tile_spawned')
            for event in starts:first.setdefault(event['slot'],event)
            for slot in range(1,expected+1):
                event=first.get(slot)
                if event is None: missing.append(slot); continue
                begin=max((r['monotonic'] for r in points(worker,'tile_spawn_begin') if r['monotonic']<=event['monotonic']),default=event['monotonic'])
                later=min((r['monotonic'] for r in starts if r['target_pid']==event['target_pid'] and r['monotonic']>event['monotonic']),default=float('inf'))
                children=[t for t in traces if t['pid']==event['target_pid']
                          and t['parent'].get('pid')==worker['pid']
                          and t['parent'].get('creation_filetime')==worker['created']
                          and any(begin<=r['monotonic']<later for r in t['rows'] if r.get('event')=='process_entry')]
                if len(children)!=1: missing.append(slot); continue
                child_rows.append((slot,children[0]))
        else:
            child_rows=[(slot,worker) for slot in range(1,expected+1)]
        tiles=[]
        for slot,trace in child_rows:
            events={name:next((r for r in points(trace,name) if r.get('slot')==slot),None)
                    for name in ('first_frame_ready','first_game_gdi_submit','first_unfaded_gdi_submit')}
            tiles.append(dict(slot=slot,file=trace['file'],
                              **{name:elapsed(root,event) for name,event in events.items()}))
        def aggregate(name):
            values=[t[name] for t in tiles if t[name] is not None]
            return dict(first=min(values) if values else None,
                        all_initial=max(values) if len(values)==expected and expected>0 else None,
                        recorded=len(values),expected=expected)
        result.append(dict(worker_file=worker['file'],root_file=root['file'] if root else None,
            origin='OS process creation; entry offset uses wall clock, later intervals monotonic',
            physical_visibility_verified=False, independent=layout['independent'],
            first_generation_only=True,missing_slots=missing,tiles=tiles,
            metrics={name:aggregate(name) for name in ('first_frame_ready','first_game_gdi_submit','first_unfaded_gdi_submit')},
            stages=[{k:r[k] for k in ('name','elapsed_seconds','completed','system') if k in r}
                    for r in worker['rows'] if r.get('event')=='startup_point' and 'elapsed_seconds' in r]))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs',type=Path)
    args=parser.parse_args()
    print(json.dumps(summarize(read_traces(args.logs)),ensure_ascii=False,indent=2))
