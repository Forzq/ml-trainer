Option Explicit
Dim shell, fso, root, pythonPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonPath = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonPath) Then
    MsgBox "Run Setup.cmd in the project folder first.", 48, "ML Trainer"
    WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & root & "\launcher.pyw" & Chr(34), 0, False
