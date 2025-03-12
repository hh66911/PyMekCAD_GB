import drawer
from importlib import reload
import parts
import pythoncom
import win32com.client
import math
import re
import numpy as np
import pandas as pd
import time
import winsound

wincad = win32com.client.Dispatch("AutoCAD.Application")
doc = wincad.ActiveDocument
doc.Utility.Prompt("Hello! Autocad from pywin32com.\n")
msp = doc.ModelSpace

gear_data = r'C:\Users\h1318\Documents\学校专业课\机械设计课设\output\减速器数据 (1) - 副本.xlsx'
gear_data = pd.read_excel(gear_data)
gear_data = gear_data.set_index('项目')


mydrawer = drawer.Drawer(wincad)
model = wincad.ActiveDocument.ModelSpace


def get_data(key):
    klist = gear_data.index.tolist()
    idx = np.where([s.startswith(key) for s in klist])
    key = klist[idx[0].item()]
    return gear_data.loc[key, :]


module = get_data('模数').astype(np.float32)
teeth = get_data('齿数').astype(np.int32)
beta = get_data('螺旋角')
beta = [re.match(r"(\d+)°(\d+)'([\d.]+)″", b).groups() for b in beta]
deg = [int(dms[0]) + int(dms[1]) / 60 + float(dms[2]) / 3600 for dms in beta]
deg = [parts.Angle(d) for d in deg]
bold = get_data('齿宽').astype(np.int32)

d_holes = [30, 34, 40, 55]
gears: list[parts.Gear] = []
for m, z, b, a, dh in zip(module, teeth, bold, deg, d_holes):
    if float(a) > 0:
        g = parts.Gear(m, z, b, dh,
                       None, a)
    else:
        g = parts.Gear(m, z, b, dh)
    gears.append(g)

gears[0].rotation = parts.GearRotation.CLOCKWISE
gears[1].rotation = parts.GearRotation.COUTER_CLOCKWISE

d_holes = np.array([25, 30, 55]) // 5
print(d_holes.astype(np.int32))
bearings = []
for d in d_holes:
    bearings.append(
        parts.Bearing(f'70{int(d):02d}AC')
    )

box = parts.Box(gears, bearings)

# box.draw(mydrawer, parts.ViewPort.TOP2BOTTOM, (0, 0), (0, 2))
s1 = box.gen_shaft1(20, 20)
s2 = box.gen_shaft2(30, 30)
s3 = box.gen_shaft3(55)
s1.add_keyway(s1.add_coupling(parts._StartFeature(0), 40), 25)
s3.process_features()
s3.add_keyway(s3.add_coupling(parts._EndFeature(s3.length), 76), 63)


# box.bearing_covers[0][0].draw(mydrawer, (0, 0), (0, 1))
box.draw(mydrawer, parts.ViewPort.TOP2BOTTOM, (0, 0), (0, 1))

mydrawer.update()
winsound.MessageBeep(winsound.MB_ICONHAND)
