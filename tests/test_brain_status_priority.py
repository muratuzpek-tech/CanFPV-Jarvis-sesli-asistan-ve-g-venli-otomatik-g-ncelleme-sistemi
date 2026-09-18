# paket 'pip install -e .' ile kurulu; sys.path hilesine gerek yok
from jarvis.main import JarvisLive
import jarvis.core.brain_orchestrator as bo

calls = []
def fake_tool(parameters=None, player=None):
    calls.append(parameters)
    return 'ok'
bo.brain_team_tool = fake_tool

class UI:
    def write_log(self, value): pass

obj = JarvisLive.__new__(JarvisLive)
obj._loop = object(); obj.session = object(); obj.ui = UI(); obj.speak = lambda value: None
obj._on_text_command('AI takımının görev durumunu göster.')
assert calls and calls[0]['action'] == 'status', calls
calls.clear()
obj._on_text_command('AI takımının sağlık durumunu göster.')
assert calls and calls[0]['action'] == 'health', calls
print('BRAIN_STATUS_PRIORITY_OK')
