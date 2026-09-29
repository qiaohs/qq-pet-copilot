Option Explicit

Dim wsh, fso, rootDir, batchFile, pythonwFile, mainFile, launchLine, result
Set wsh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

rootDir = fso.GetParentFolderName(WScript.ScriptFullName)
batchFile = fso.BuildPath(rootDir, "run_windows_real_device.bat")
pythonwFile = fso.BuildPath(rootDir, ".venv\Scripts\pythonw.exe")
mainFile = fso.BuildPath(rootDir, "main.py")
wsh.CurrentDirectory = rootDir

' Use pythonw directly after setup. Show the BAT only for first-time setup.
If fso.FileExists(pythonwFile) Then
    launchLine = Chr(34) & pythonwFile & Chr(34) & " " & Chr(34) & mainFile & Chr(34)
    result = wsh.Run(launchLine, 0, False)
Else
    result = wsh.Run(Chr(34) & batchFile & Chr(34), 1, False)
End If
