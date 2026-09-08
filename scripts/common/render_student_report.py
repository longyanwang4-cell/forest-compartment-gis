#!/usr/bin/env python3
from __future__ import annotations
import argparse, html, json
from pathlib import Path

def load(path: Path):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception: return {}

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--workflow-root',required=True); ap.add_argument('--output',required=True); args=ap.parse_args()
    root=Path(args.workflow_root); state=load(root/'00_Workflow'/'workflow_state.json'); summary=load(root/'00_Workflow'/'workflow_summary.json')
    issues=summary.get('issues') or state.get('issues') or []
    rows=''.join(f"<tr><td>{html.escape(str(x.get('code','UNKNOWN')))}</td><td>{html.escape(str(x.get('severity','unknown')))}</td></tr>" for x in issues)
    links=[]
    for name in ['gdb_quality_report.json','quality_report.json','topology_report.json','provenance.json','field_form_schema.json']:
        matches=list(root.rglob(name))
        if matches: links.append(f"<li>{html.escape(str(matches[0].relative_to(root)))}</li>")
    doc=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>森林GIS工作流报告</title>
<style>body{{font-family:Arial,"Microsoft YaHei";max-width:900px;margin:40px auto;line-height:1.65}}code{{background:#f3f3f3;padding:2px 5px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:8px}}.ok{{color:#087f23}}.warn{{color:#a15c00}}</style>
<h1>森林经理学实习 GIS 工作流报告</h1><p>状态：<strong class="{'ok' if state.get('status')=='SUCCESS' else 'warn'}">{html.escape(str(state.get('status','UNKNOWN')))}</strong></p>
<p>执行模式：<code>{html.escape(str(state.get('execution_mode','standard')))}</code>；恢复次数：{state.get('resume_count',0)}</p>
<h2>已完成步骤</h2><p>{html.escape(' → '.join(state.get('completed_steps') or []))}</p>
<h2>需要核查</h2><table><tr><th>代码</th><th>严重度</th></tr>{rows or '<tr><td colspan="2">无</td></tr>'}</table>
<h2>主要文件</h2><ul>{''.join(links) or '<li>尚未生成</li>'}</ul>
<p>本报告只汇总程序记录；候选小班仍需结合影像判读和外业踏查由学生与老师确认。</p></html>'''
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(doc,encoding='utf-8')
    print(out); return 0
if __name__=='__main__': raise SystemExit(main())
