p = open(r'C:\Users\Murat\Desktop\CanFPV_Jarvis_v3\CanFPV Jarvis v3\main.py', encoding='utf-8').read()
print('IMPORT OK' if 'from actions.self_heal' in p else 'IMPORT MISSING')
print('DECL OK' if 'self_heal' in p and 'diagnose' in p else 'DECL MISSING')
print('HANDLER OK' if 'elif name == ' + chr(34) + 'self_heal' + chr(34) in p else 'HANDLER MISSING')
