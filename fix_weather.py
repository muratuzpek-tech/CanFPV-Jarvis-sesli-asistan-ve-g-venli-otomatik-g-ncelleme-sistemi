p = 'actions/weather_report.py'
c = open(p, encoding='utf-8').read()
c = c.replace('    raise RuntimeError("Intentional test error for self-heal")\n', '')
open(p, 'w', encoding='utf-8').write(c)
print('weather_report.py restored - no RuntimeError')
