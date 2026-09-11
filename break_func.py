p = 'actions/weather_report.py'
c = open(p, encoding='utf-8').read()
old = 'def weather_action('
idx = c.find(old)
if idx >= 0:
    end = c.find(':', idx) + 1
    c = c[:end] + '\n    raise RuntimeError("KASITLI_TEST: Bu bir self-heal testidir")' + c[end:]
    open(p, 'w', encoding='utf-8').write(c)
    print('WEATHER FUNCTION BROKEN OK')
else:
    print('FUNCTION NOT FOUND')
