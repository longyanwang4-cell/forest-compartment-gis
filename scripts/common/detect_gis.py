#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, platform, shutil, subprocess
from pathlib import Path


def run(cmd, timeout=40):
    if isinstance(cmd, str):
        raise TypeError('detect_gis.run requires an argument list; string commands are rejected')
    try:
        cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout,shell=False)
        return cp.returncode,cp.stdout.strip()
    except Exception as e:
        return 999,str(e)


def existing(items):
    for x in items:
        if not x: continue
        p=Path(str(x).strip().strip('"'))
        try:
            if p.exists(): return str(p)
        except OSError: pass
    return None


def registry_roots():
    if platform.system()!='Windows': return []
    try: import winreg
    except Exception: return []
    result=[]
    for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
        for access in [winreg.KEY_READ,winreg.KEY_READ|getattr(winreg,'KEY_WOW64_64KEY',0),winreg.KEY_READ|getattr(winreg,'KEY_WOW64_32KEY',0)]:
            for keyname in [r'SOFTWARE\ESRI\ArcGISPro',r'SOFTWARE\WOW6432Node\ESRI\ArcGISPro',r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ArcGISPro.exe']:
                try:
                    with winreg.OpenKey(hive,keyname,0,access) as k:
                        for vn in ['InstallDir','InstallLocation','InstallPath','','Path']:
                            try: v,_=winreg.QueryValueEx(k,vn)
                            except OSError: continue
                            if v:
                                p=Path(str(v).strip().strip('"'))
                                if p.name.lower()=='arcgispro.exe': p=p.parent.parent
                                result.append(str(p))
                except OSError: pass
    return list(dict.fromkeys(result))


def detect_arcgis_pro():
    roots=[]
    for value in [os.getenv('ARCGIS_PRO_ROOT'),*registry_roots()]:
        if value: roots.append(Path(value))
    for base in [os.getenv('PROGRAMFILES'),os.getenv('ProgramW6432'),os.getenv('PROGRAMFILES(X86)'),os.getenv('LOCALAPPDATA')]:
        if base:
            b=Path(base); roots += [b/'ArcGIS'/'Pro',b/'Programs'/'ArcGIS'/'Pro']
    for letter in 'CDEFGHIJ':
        d=Path(f'{letter}:\\')
        if d.exists(): roots += [d/'ArcGIS'/'Pro',d/'Program Files'/'ArcGIS'/'Pro',d/'Apps'/'ArcGIS'/'Pro']
    propy=[os.getenv('ARCGIS_PROPY'),shutil.which('propy.bat')]
    exe=[os.getenv('ARCGIS_PRO_EXE'),shutil.which('ArcGISPro.exe')]
    py=[]
    for r in roots:
        if r.name.lower()=='bin': r=r.parent
        propy += [r/'bin'/'Python'/'scripts'/'propy.bat']
        exe += [r/'bin'/'ArcGISPro.exe']
        py += [r/'bin'/'Python'/'envs'/'arcgispro-py3'/'python.exe']
    p=existing(propy); e=existing(exe); python=existing(py); version=None; arcpy_ok=False; error=None
    if p:
        rc,out=run([p,'-c','import arcpy,json;print(json.dumps(arcpy.GetInstallInfo(),ensure_ascii=False))'],60)
        if rc==0:
            arcpy_ok=True
            try: version=json.loads(out.splitlines()[-1]).get('Version')
            except Exception: version=out[-300:]
        else: error=out[-1000:]
    return {'installed':bool(p or e),'ready':bool(p and arcpy_ok),'version':version,'propy':p,'python':python,'exe':e,'arcpy_import_ok':arcpy_ok,'error':error}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--json',action='store_true'); args=ap.parse_args()
    data={'platform':platform.system(),'python':shutil.which('python'),'py':shutil.which('py'),'arcgis_pro':detect_arcgis_pro()}
    if platform.system()=='Windows':
        data['arcmap_10_8']={'python':existing([r'C:\Python27\ArcGIS10.8\python.exe',r'C:\Python27\ArcGISx6410.8\python.exe'])}
        q=shutil.which('qgis_process'); data['qgis']={'qgis_process':q,'installed':bool(q)}
    else:
        data['arcmap_10_8']={'python':None}; q=shutil.which('qgis_process'); data['qgis']={'qgis_process':q,'installed':bool(q)}
    data['recommended_backend']='arcgis-pro-3.5' if data['arcgis_pro']['ready'] else ('qgis' if data['qgis']['installed'] else ('arcmap-10.8' if data['arcmap_10_8']['python'] else 'common-only'))
    print(json.dumps(data,ensure_ascii=False,indent=2) if args.json else data)
if __name__=='__main__': main()
