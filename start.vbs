Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "C:\Your Path\run_script.bat" & chr(34), 0
Set WshShell = Nothing