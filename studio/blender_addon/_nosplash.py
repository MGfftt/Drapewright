# Turns the startup splash off for the screenshot scripts (it covers the viewport).
# 5.2 has no `show_corner_splash` (removed years ago) -> guard with getattr, otherwise the
# whole script dies before save_userpref and the splash comes back.
import bpy

view = bpy.context.preferences.view
view.show_splash = False
for attr in ('show_corner_splash', 'show_splash_corner'):
    if hasattr(view, attr):
        setattr(view, attr, False)
bpy.ops.wm.save_userpref()
print('PREFS_SAVED splash=%s' % bpy.context.preferences.view.show_splash)