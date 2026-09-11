p = 'actions/self_heal.py'
c = open(p, encoding='utf-8').read()

old = '    except SyntaxError:\n        return False\n    except:\n        return True'
new = '    except Exception as e:\n        print("[SELF-HEAL] Test failed:", e)\n        return False'

if old in c:
    c = c.replace(old, new)
    open(p, 'w', encoding='utf-8').write(c)
    print('self_heal.py FIXED')
else:
    print('PATTERN NOT FOUND - checking current code...')
    for i, line in enumerate(c.splitlines()):
        if 'except' in line:
            print(f'  Line {i+1}: {line}')
