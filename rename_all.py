p = 'ui.py'
c = open(p, encoding='utf-8').read()

# Replace CanFPV references
c = c.replace('J.A.R.V.I.S — CanFPV', 'J.A.R.V.I.S — MuratJarvis')
c = c.replace('_badge(\"CanFPV\"', '_badge(\"MuratJarvis\"')
c = c.replace('CanFPV  ·  Jarvis by CanFPV v3  ·  GIZLI', 'MuratJarvis  ·  AI Assistant  ·  GIZLI')
c = c.replace('© CanFPV', '© MuratJarvis')

open(p, 'w', encoding='utf-8').write(c)
print('ui.py UPDATED - CanFPV -> MuratJarvis')

# Also check prompt.txt
p2 = 'core/prompt.txt'
try:
    c2 = open(p2, encoding='utf-8').read()
    if 'CanFPV' in c2 or 'canfpv' in c2.lower():
        c2 = c2.replace('CanFPV', 'MuratJarvis')
        open(p2, 'w', encoding='utf-8').write(c2)
        print('prompt.txt UPDATED')
    else:
        print('prompt.txt - no CanFPV found')
except:
    print('prompt.txt - not found')
