bl_info = {
    "name": "Add Blender to your desktop menu",
    "blender": (2, 80, 0),
    "category": "System",
    "location": "Top Bar > Blender Icon > System > Lancher Entry and Desktop Icon"
}

from typing import Literal
from subprocess import check_output, PIPE, CalledProcessError
from shutil import which, copy
from tempfile import TemporaryDirectory
from os.path import join as join_path
from pathlib import Path

import re
import os
import bpy
import platform

type OperatorReturnStatus = Literal['RUNNING_MODAL', 'CANCELLED', 'FINISHED', 'PASS_THROUGH', 'INTERFACE']

# Very weird and confusing quoting rules.
# See: https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html
# See also: https://specifications.freedesktop.org/desktop-entry/latest/value-types.html
_XDG_SPECIAL = re.compile(r'[ "\n\t\r`$\\]')
_XDG_ESC_CHARS = {
    ' ': r'\s',
    '"': r'\"',
    '\t': r'\t',
    '\r': r'\r',
    '\\': r'\\\\',
    '`': r'\`',
    '$': r'\\$',
}

def xdg_quote_exec(text: str) -> str:
    esc_chars = _XDG_ESC_CHARS
    esc_text = _XDG_SPECIAL.sub(lambda m: esc_chars[m[0]], text)
    return f'"{esc_text}"'

# TODO: [x] install menu
# TODO: [x] install icon for theme. needs Desktop restart sometimes.
# TODO: [x] install desktop icon
# TODO: [x] install mime type (file type association)
# TODO: [x] uninstall option
# TODO: [x] version suffix option
# TODO: [x] Windows support (only tested in Wine on Linux)
# TODO: [ ] macOS support

_MIME_XML = '''\
<?xml version="1.0" encoding="utf-8"?>
<mime-type xmlns="http://www.freedesktop.org/standards/shared-mime-info" type="application/x-blender">
    <comment>Blender scene</comment>
    <generic-icon name="image-x-generic"/>
    <glob pattern="*.blend"/>
    <glob pattern="*.BLEND"/>
    <glob pattern="*.blender"/>
</mime-type>
'''

_SHORTCUT_VBS = '''\
On Error Resume Next

If WScript.Arguments.Count <> 2 Then
    WScript.Echo("Error: Illegal number of arguments.")
    WScript.Quit(1)
End If

Set FSO = CreateObject("Scripting.FileSystemObject")
TargetPath = FSO.GetAbsolutePathName(WScript.Arguments(0))
WorkingDirectory = FSO.GetParentFolderName(TargetPath)
Set shortcut = CreateObject("WScript.Shell").CreateShortcut(WScript.Arguments(1))
shortcut.TargetPath = TargetPath
shortcut.WorkingDirectory = WorkingDirectory
shortcut.Save()

If Err.Number <> 0 Then
    WScript.Echo("Error: " & Err.Number)
    If Err.Description <> "" Then
        WScript.Echo("Description: " & Err.Description)
    End If
    If Err.Source <> "" Then
        WScript.Echo("Source: " & Err.Source)
    End If
    WScript.Quit(1)
End If
'''

_SYSTEM = platform.system()

def _pretty_system():
    return 'macOS' if _SYSTEM == 'Darwin' else _SYSTEM

class SystemDesktopMenu(bpy.types.Operator):
    """Add Blender to your desktop"""
    bl_idname = "system.desktop_menu"
    bl_label = "Lancher Entry and Desktop Icon"
    bl_options = {'REGISTER'}
    bl_description = """\
Add Blender to your program launcher menu, file type associactions, and/or as a desktop icon."""

    install_menu: bpy.props.BoolProperty(name="Launcher menu entry", default=True) # pyright: ignore[reportInvalidTypeForm]
    if os.name == 'posix':
        install_icon: bpy.props.BoolProperty(name="Blender icon", default=True, description="""\
Add the Blender icon to your desktop icon theme. Needed for the menu entry to show the correct icon.
This might require a restart to become visible.""") # pyright: ignore[reportInvalidTypeForm]
    install_desktop_icon: bpy.props.BoolProperty(name="Icon on desktop", default=False) # pyright: ignore[reportInvalidTypeForm]
    install_mime: bpy.props.BoolProperty(name="File type association", default=True, description="Make Blender the default application for .blend files.") # pyright: ignore[reportInvalidTypeForm]
    version_suffix: bpy.props.BoolProperty(name=f"Include version suffix", default=False, description=f"""\
Adds Blender version as a program name suffix, enabling multiple Blenders: "Blender {bpy.app.version_string}"
NOTE: If you want to uninstall the old menu entries you have to use the old Blender version or do it manually.""") # pyright: ignore[reportInvalidTypeForm]
    uninstall: bpy.props.BoolProperty(name="Uninstall", default=False, description="WARNING: Uninstalls selected options instead of installing them!") # pyright: ignore[reportInvalidTypeForm]

    def _xdg_tool_not_found(self, tool: str) -> None:
        system = _pretty_system()
        if system == 'Linux':
            self.report({'ERROR'}, f'{tool} not found. You need to install XDG tools.')
        else:
            self.report({'ERROR'}, f'{tool} not found. Currently only Linux with installed XDG tools is supported. Your system is {system}.')

    def _show_info(self, message: str) -> None:
        def draw_msg(self, context):
            self.layout.label(text=message)

        bpy.context.window_manager.popup_menu(draw_msg, title=self.bl_label, icon="INFO")

    def _xdg_execute(self, context: bpy.types.Context) -> set[OperatorReturnStatus]:
        blender_bin = Path(bpy.app.binary_path)
        blender_dir = blender_bin.parent
        blender_desktop = blender_dir.joinpath('blender.desktop')
        blender_svg = blender_dir.joinpath('blender.svg')

        install_icon: bool = self.install_icon
        install_menu: bool = self.install_menu
        install_desktop_icon: bool = self.install_desktop_icon
        install_mime: bool = self.install_mime
        uninstall: bool = self.uninstall
        version_suffix: bool = self.version_suffix

        xdg_desktop_menu: str|None = None
        xdg_desktop_icon: str|None = None
        xdg_mime: str|None = None

        if install_icon:
            xdg_icon_ressource = which('xdg-icon-resource')
            if not blender_svg.exists():
                self.report({'ERROR'}, 'blender.svg icon file is missing!')
                return {'CANCELLED'}
        else:
            xdg_icon_ressource = None

        if install_menu and (xdg_desktop_menu := which('xdg-desktop-menu')) is None:
            self._xdg_tool_not_found('xdg-desktop-menu')
            return {'CANCELLED'}

        if install_desktop_icon and (xdg_desktop_icon := which('xdg-desktop-icon')) is None:
            self._xdg_tool_not_found('xdg-desktop-icon')
            return {'CANCELLED'}

        if install_mime and (xdg_mime := which('xdg-mime')) is None:
            self._xdg_tool_not_found('xdg-mime')
            return {'CANCELLED'}

        if not (install_icon or install_menu or install_desktop_icon or install_mime):
            msg = 'Nothing to do.'
            self.report({'INFO'}, msg)
            self._show_info(msg)
            return {'CANCELLED'}

        KDE_SESSION_VERSION = os.environ.get('KDE_SESSION_VERSION')
        try:
            kde_version = int(KDE_SESSION_VERSION, 10) if KDE_SESSION_VERSION else 0
        except:
            kde_version = 0

        if kde_version > 4 and which('qtpaths') is None and os.path.exists('/usr/lib/qt6/bin/qtpaths'):
            # HACK: Fixing bug in some Linux distributions (e.g. TuxedoOS) where xdg-mime is a script that
            #       uses qtpaths but only qtpaths6 is in $PATH.
            PATH = os.environ.get('PATH')
            qt6_bin_dir = '/usr/lib/qt6/bin/'
            PATH = f'{PATH}:{qt6_bin_dir}' if PATH else qt6_bin_dir
        else:
            PATH = None

        things: list[str] = []

        with TemporaryDirectory() as tmpdir:
            if install_icon:
                XDG_DATA_HOME = os.environ.get("XDG_DATA_HOME")
                share_dir = Path(XDG_DATA_HOME) if XDG_DATA_HOME else Path.home().joinpath('.local', 'share')
                icon_dir = share_dir.joinpath('icons', 'hicolor', 'scalable', 'apps')

                if uninstall:
                    icon_dir.joinpath('blender.svg').unlink(missing_ok=True)
                else:
                    icon_dir.mkdir(parents=True, exist_ok=True)
                    copy(blender_svg, icon_dir.joinpath('blender.svg'))

                if xdg_icon_ressource is not None:
                    # Icons *can* be SVG, but xdg-icon-ressource install only accepts PNG or XPM.
                    # So instead we just manually copy/delete the icon and run xdg-icon-ressource forceupdate.
                    if not self._run([xdg_icon_ressource, 'forceupdate', '--theme', 'hicolor', '--mode', 'user']):
                        return {'CANCELLED'}
                else:
                    self.report({'WARNING'}, 'xdg-icon-ressource not found. You might need to refresh your icon theme through your desktop environment.')

                things.append('icon')

            if install_menu or install_desktop_icon or install_mime:
                tmp_blender_desktop = join_path(
                    tmpdir,
                    f'blender-{bpy.app.version[0]}-{bpy.app.version[1]}-{bpy.app.version[2]}.desktop'
                    if version_suffix else 'blender.desktop')

                with open(tmp_blender_desktop, 'wt') as tmp_fp:
                    try:
                        has_exec = False
                        exec_line = f'Exec={xdg_quote_exec(str(blender_bin))} %f\n'

                        with open(blender_desktop, 'rt') as blender_desktop_fp:
                            for line in blender_desktop_fp:
                                if line.startswith('Exec='):
                                    tmp_fp.write(exec_line)
                                    has_exec = True
                                elif version_suffix and line.startswith('Name='):
                                    tmp_fp.write(f'Name=Blender {bpy.app.version_string}\n')
                                else:
                                    tmp_fp.write(line)

                        if not has_exec:
                            tmp_fp.write(exec_line)

                    except FileNotFoundError as exc:
                        self.report({'ERROR'}, f'{exc.filename or blender_desktop} not found!')
                        return {'CANCELLED'}

                action = 'uninstall' if uninstall else 'install'

                if install_menu and xdg_desktop_menu is not None:
                    if not self._run([xdg_desktop_menu, action, '--mode', 'user', '--novendor', tmp_blender_desktop], path=PATH):
                        return {'CANCELLED'}

                    things.append('desktop menu entry')

                if install_desktop_icon and xdg_desktop_icon:
                    if not self._run([xdg_desktop_icon, action, '--novendor', tmp_blender_desktop], path=PATH):
                        return {'CANCELLED'}

                    things.append('desktop icon')

                if install_mime and xdg_mime:
                    tmp_mime = join_path(tmpdir, 'x-blender.xml')

                    with open(tmp_mime, 'wt') as tmp_fp:
                        tmp_fp.write(_MIME_XML)

                    if uninstall:
                        if not self._run([xdg_mime, 'uninstall', '--mode', 'user', tmp_mime], path=PATH):
                            return {'CANCELLED'}
                    else:
                        if not self._run([xdg_mime, 'install', '--mode', 'user', '--novendor', tmp_mime], path=PATH):
                            return {'CANCELLED'}

                        if not self._run([xdg_mime, 'default', tmp_blender_desktop, 'application/x-blender'], path=PATH):
                            return {'CANCELLED'}

                    things.append('file type association')

        if len(things) > 1:
            en_list = ', '.join(things[:-1]) + ', and ' + things[-1]
        elif len(things) == 1:
            en_list = things[0]
        else:
            return {'CANCELLED'}

        if uninstall:
            msg = f'Uninstalled {en_list}.'
        else:
            msg = f'Installed {en_list}.'

        self.report({'INFO'}, msg)
        self._show_info(msg)

        return {'FINISHED'}

    def _run(self, cmd: list[str], path: str|None=None, cwd: str|None=None) -> bool:
        try:
            check_output(
                cmd,
                stderr=PIPE,
                env={ **os.environ, 'PATH': path } if path else None,
                cwd=cwd,
                encoding='UTF-8',
                errors='backslashreplace',
            )
        except CalledProcessError as exc:
            if isinstance(exc.stderr, bytes):
                output = exc.stderr.decode(encoding='UTF-8', errors='backslashreplace')
            elif isinstance(exc.stderr, str):
                output = exc.stderr
            else:
                output = str(exc.output or '')

            msg = f'Error running {cmd[0]}!\nStatus code: {exc.returncode}'

            if output:
                msg = f'{msg}\nCommand output:\n    {output.replace("\n", "\n    ")}'

            self.report({'ERROR'}, msg)

            return False

        return True

    def _win32_shortcut(self, target: str, source: str, cwd: str, shortcut_vbs: str) -> bool:
        try:
            check_output(
                ['cscript', '/nologo', shortcut_vbs, target, source],
                cwd=cwd,
                encoding='UTF-8',
                errors='backslashreplace',
            )
        except CalledProcessError as exc:
            output = str(exc.output or '')
            msg = f'Error creating shortcut to "{target}" at "{source}"!'

            if output:
                msg = f'{msg}\nCommand output:\n    {output.replace("\n", "\n    ")}'

            self.report({'ERROR'}, msg)

            return False

        return True

    def _win32_execute(self, context: bpy.types.Context) -> set[OperatorReturnStatus]:
        blender_bin = bpy.app.binary_path

        install_menu: bool = self.install_menu
        install_desktop_icon: bool = self.install_desktop_icon
        install_mime: bool = self.install_mime
        uninstall: bool = self.uninstall
        version_suffix: bool = self.version_suffix

        from winreg import (
            HKEY_CLASSES_ROOT, HKEY_CURRENT_USER, KEY_ENUMERATE_SUB_KEYS, REG_SZ, # pyright: ignore[reportAttributeAccessIssue]
            CreateKey, OpenKey, CloseKey, DeleteKey, EnumKey, SetValueEx, QueryValueEx, # pyright: ignore[reportAttributeAccessIssue]
         )

        def winreg_delete_tree(hkey, subkey):
            hsubkey = OpenKey(hkey, subkey, access=KEY_ENUMERATE_SUB_KEYS)
            try:
                while True:
                    try:
                        winreg_delete_tree(hsubkey, EnumKey(hsubkey, 0))
                    except OSError:
                        break
                DeleteKey(hkey, subkey)
            finally:
                CloseKey(hsubkey)

        prog_id = f'blender.{bpy.app.version[0]}.{bpy.app.version[1]}.{bpy.app.version[2]}' if version_suffix else 'blender'
        pretty_name = f'Blender {bpy.app.version_string}' if version_suffix else 'Blender'

        if install_mime:
            if uninstall:
                winreg_delete_tree(HKEY_CLASSES_ROOT, '.blend')
                winreg_delete_tree(HKEY_CLASSES_ROOT, prog_id)
            else:
                hkey = CreateKey(HKEY_CLASSES_ROOT, '.blend')
                try:
                    SetValueEx(hkey, None, 0, REG_SZ, prog_id)
                    SetValueEx(hkey, "Content Type", 0, REG_SZ, "application/x-blender")
                finally:
                    CloseKey(hkey)

                hkey = CreateKey(HKEY_CLASSES_ROOT, prog_id)
                try:
                    SetValueEx(hkey, None, 0, REG_SZ, pretty_name)
                    SetValueEx(hkey, "AppUserModelId", 0, REG_SZ, prog_id)
                finally:
                    CloseKey(hkey)

                hkey = CreateKey(HKEY_CLASSES_ROOT, f'{prog_id}\\shell\\open')
                try:
                    SetValueEx(hkey, "FriendlyAppName", 0, REG_SZ, pretty_name)
                finally:
                    CloseKey(hkey)

                hkey = CreateKey(HKEY_CLASSES_ROOT, f'{prog_id}\\shell\\open\\command')
                try:
                    SetValueEx(hkey, None, 0, REG_SZ, f'"{blender_bin}" "%1"')
                finally:
                    CloseKey(hkey)

                hkey = CreateKey(HKEY_CLASSES_ROOT, f'{prog_id}\\DefaultIcon')
                try:
                    SetValueEx(hkey, None, 0, REG_SZ, f'"{blender_bin}", 1')
                finally:
                    CloseKey(hkey)

        if install_menu or install_desktop_icon:
            programs_dir_str = None
            desktop_dir_str = None

            hkey = OpenKey(HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Shell Folders")
            try:
                try:
                    programs_dir_str, value_type = QueryValueEx(hkey, "Programs")
                    if value_type != REG_SZ:
                        programs_dir_str = None

                except FileNotFoundError:
                    programs_dir_str = None

                try:
                    desktop_dir_str, value_type = QueryValueEx(hkey, "Desktop")
                    if value_type != REG_SZ:
                        desktop_dir_str = None

                except FileNotFoundError:
                    desktop_dir_str = None
            finally:
                CloseKey(hkey)

            if programs_dir_str is None:
                programs_dir = Path.home().joinpath('AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs')
            else:
                programs_dir = Path(programs_dir_str)

            if desktop_dir_str is None:
                desktop_dir = Path.home().joinpath('Desktop')
            else:
                desktop_dir = Path(desktop_dir_str)

            tmpdir = TemporaryDirectory()

            try:
                shortcut_vbs = join_path(tmpdir.name, "Shortcut.vbs")
                with open(shortcut_vbs, "wt") as tmp_fp:
                    tmp_fp.write(_SHORTCUT_VBS)

                link_name = f'{pretty_name}.lnk'

                if install_menu:
                    programs_dir.mkdir(parents=True, exist_ok=True)
                    menu_entry_path = str(programs_dir.joinpath(link_name))
                    if not self._win32_shortcut(shortcut_vbs=shortcut_vbs, target=blender_bin, source=menu_entry_path, cwd=tmpdir.name):
                        return {'CANCELLED'}

                if install_desktop_icon:
                    desktop_dir.mkdir(parents=True, exist_ok=True)
                    desktop_icon_path = str(desktop_dir.joinpath(link_name))
                    if not self._win32_shortcut(shortcut_vbs=shortcut_vbs, target=blender_bin, source=desktop_icon_path, cwd=tmpdir.name):
                        return {'CANCELLED'}

            finally:
                try:
                    tmpdir.cleanup()
                except PermissionError as exc:
                    # no idea why this happens
                    self.report({'WARNING'}, f'Error cleaning up temporary files: {exc}')

        return {'FINISHED'}

    def _unsupported_os_execute(self, context: bpy.types.Context) -> set[OperatorReturnStatus]:
        system = _pretty_system()
        self.report({'ERROR'}, f'Currently only Linux with installed XDG tools is supported. Your system is {system}.')
        return {'CANCELLED'}

    if _SYSTEM == 'Darwin':
        # macOS also has os.name == 'posix'
        # TODO: macOS
        execute = _unsupported_os_execute
    elif os.name == 'posix':
        # Linux (and *BSD?)
        execute = _xdg_execute
    elif _SYSTEM == 'Windows':
        # Windows
        execute = _win32_execute
    else:
        execute = _unsupported_os_execute

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[OperatorReturnStatus]:
        if _SYSTEM == 'Darwin' or (_SYSTEM != 'Windows' and os.name != 'posix'):
            return self._unsupported_os_execute(context)

        return context.window_manager.invoke_props_dialog(self)

def menu_func(self, context) -> None:
    self.layout.operator(SystemDesktopMenu.bl_idname)

def register():
    bpy.utils.register_class(SystemDesktopMenu)
    bpy.types.TOPBAR_MT_blender_system.append(menu_func) # type: ignore

def unregister():
    bpy.utils.unregister_class(SystemDesktopMenu)
    bpy.types.TOPBAR_MT_blender_system.remove(menu_func) # type: ignore

if __name__ == "__main__":
    register()
