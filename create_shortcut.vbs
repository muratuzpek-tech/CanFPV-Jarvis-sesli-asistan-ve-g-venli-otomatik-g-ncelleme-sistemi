Set WshShell = CreateObject("WScript.Shell")
Set oShellLink = WshShell.CreateShortcut(WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\Desktop\Jarvis.lnk")
oShellLink.TargetPath = WshShell.CurrentDirectory & "\venv\Scripts\python.exe"
oShellLink.Arguments = "main.py"
oShellLink.WorkingDirectory = WshShell.CurrentDirectory
oShellLink.Description = "MuratJarvis AI Assistant"
oShellLink.IconLocation = WshShell.CurrentDirectory & "\face.png,0"
oShellLink.Save
