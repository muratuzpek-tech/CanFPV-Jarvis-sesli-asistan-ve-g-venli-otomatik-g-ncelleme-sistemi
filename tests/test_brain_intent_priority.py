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
obj._loop = object(); obj.session = object(); obj.ui = UI()
obj.speak = lambda value: None
prompt = ('AI takımına kapsamlı bir denetim görevi ver. Planner parçalara ayırsın. '
          'Research araştırma yapsın. Hiçbir dosyayı değiştirmeyin, silmeyin, çalıştırmayın.')
obj._on_text_command(prompt)
assert calls and calls[0]['action'] == 'start', calls
calls.clear()
obj._on_text_command('AI takımının sağlık durumunu göster.')
assert calls and calls[0]['action'] == 'health', calls
print('BRAIN_INTENT_PRIORITY_OK')
