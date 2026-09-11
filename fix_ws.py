p = 'actions/web_search.py'
c = open(p, encoding='utf-8').read()
c = c.replace('gemini-2.5-flash-preview-native-audio', 'gemini-2.0-flash-001')
open(p, 'w', encoding='utf-8').write(c)
print('web_search model fixed')
