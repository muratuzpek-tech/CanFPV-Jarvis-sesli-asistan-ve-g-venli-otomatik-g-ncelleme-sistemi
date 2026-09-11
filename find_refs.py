import os, re
base = r'C:\Users\Murat\Desktop\CanFPV_Jarvis_v3\CanFPV Jarvis v3'
for root, dirs, files in os.walk(base):
    dirs[:] = [d for d in dirs if d not in ('venv', '__pycache__', 'node_modules', '.git', 'backups')]
    for f in files:
        if f.endswith(('.py', '.txt', '.json', '.md', '.html', '.yaml', '.yml', '.cfg', '.ini', '.toml')):
            fp = os.path.join(root, f)
            try:
                c = open(fp, encoding='utf-8').read()
                if 'CanFPV' in c or 'CanJarvis' in c or 'canfpv' in c.lower():
                    matches = []
                    for i, line in enumerate(c.splitlines()):
                        if 'CanFPV' in line or 'CanJarvis' in line or 'canfpv' in line.lower():
                            matches.append(f'  L{i+1}: {line.strip()[:80]}')
                    if matches:
                        rel = os.path.relpath(fp, base)
                        print(f'\n{rel}:')
                        for m in matches[:5]:
                            print(m)
            except:
                pass
